// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

// Crash reporting for the Windows build: on any crash (access violation, failed assert, abort,
// std::terminate, CRT invalid parameter, pure virtual call) a symbolized stack trace is written to
// crashes\crash-<time>.txt (and crashes\last_crash.txt) plus a minidump next to it.
// Symbols come from the PDBs the Release build now produces (see /Zi in the top CMakeLists.txt).
// A watchdog thread also reports hangs: when the game window stops answering for a few seconds,
// the main thread's stack goes to crashes\hang-<time>.txt (and crashes\last_hang.txt); the game
// is left running.

#include "CrashHandler.h"

// the full windows.h: the hang watchdog needs user32 (win32def.h leaves it out)
#include <windows.h>

#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <csignal>
#include <ctime>
#include <dbghelp.h>
#include <exception>
#include <atomic>

#pragma comment(lib, "dbghelp.lib")
#pragma comment(lib, "user32.lib")

namespace {

char crashDir[MAX_PATH] = {};
HANDLE mainThread = nullptr;

void Out(FILE* f, const char* fmt, ...)
{
	va_list ap;
	va_start(ap, fmt);
	if (f) {
		va_list ap2;
		va_copy(ap2, ap);
		vfprintf(f, fmt, ap2);
		va_end(ap2);
	}
	if (_fileno(stderr) >= 0) { // no console (started detached): stderr is invalid
		vfprintf(stderr, fmt, ap);
	}
	va_end(ap);
}

void InitSymbols()
{
	static bool done = false;
	if (done) return;
	done = true;
	SymSetOptions(SYMOPT_LOAD_LINES | SYMOPT_UNDNAME | SYMOPT_DEFERRED_LOADS | SYMOPT_FAIL_CRITICAL_ERRORS);
	SymInitialize(GetCurrentProcess(), nullptr, TRUE);
}

void WriteFrame(FILE* f, int i, DWORD64 addr)
{
	HANDLE proc = GetCurrentProcess();
	alignas(SYMBOL_INFO) static char symBuf[sizeof(SYMBOL_INFO) + 512];
	{

		char modName[MAX_PATH] = "?";
		DWORD64 modBase = SymGetModuleBase64(proc, addr);
		if (modBase) {
			char full[MAX_PATH];
			if (GetModuleFileNameA(reinterpret_cast<HMODULE>(modBase), full, MAX_PATH)) {
				const char* slash = strrchr(full, '\\');
				strncpy_s(modName, slash ? slash + 1 : full, _TRUNCATE);
			}
		}

		auto* sym = reinterpret_cast<SYMBOL_INFO*>(symBuf);
		sym->SizeOfStruct = sizeof(SYMBOL_INFO);
		sym->MaxNameLen = 511;
		DWORD64 symDisp = 0;
		const char* name = SymFromAddr(proc, addr, &symDisp, sym) ? sym->Name : "?";

		IMAGEHLP_LINE64 line {};
		line.SizeOfStruct = sizeof(line);
		DWORD lineDisp = 0;
		if (SymGetLineFromAddr64(proc, addr, &lineDisp, &line)) {
			Out(f, "  #%02d %s!%s  %s:%lu\n", i, modName, name, line.FileName, line.LineNumber);
		} else {
			Out(f, "  #%02d %s!%s +0x%llx\n", i, modName, name, symDisp);
		}
	}
}

// the crashing context (from an exception), or a suspended thread's
void WriteStack(FILE* f, CONTEXT ctx, HANDLE thread = GetCurrentThread())
{
	InitSymbols();
	STACKFRAME64 frame {};
	frame.AddrPC.Offset = ctx.Rip;
	frame.AddrPC.Mode = AddrModeFlat;
	frame.AddrFrame.Offset = ctx.Rbp;
	frame.AddrFrame.Mode = AddrModeFlat;
	frame.AddrStack.Offset = ctx.Rsp;
	frame.AddrStack.Mode = AddrModeFlat;
	for (int i = 0; i < 64; ++i) {
		if (!StackWalk64(IMAGE_FILE_MACHINE_AMD64, GetCurrentProcess(), thread, &frame, &ctx, nullptr, SymFunctionTableAccess64, SymGetModuleBase64, nullptr)) {
			break;
		}
		if (frame.AddrPC.Offset == 0) break;
		WriteFrame(f, i, frame.AddrPC.Offset);
	}
}

// the current call stack (abort, terminate, CRT handlers)
void WriteCurrentStack(FILE* f)
{
	InitSymbols();
	void* frames[62];
	USHORT n = CaptureStackBackTrace(0, 62, frames, nullptr);
	for (USHORT i = 0; i < n; ++i) {
		WriteFrame(f, i, reinterpret_cast<DWORD64>(frames[i]));
	}
}

void Report(const char* reason, EXCEPTION_POINTERS* ep)
{
	// first crash wins; a crash inside the report (or on another thread meanwhile) just waits/exits
	static std::atomic<DWORD> owner { 0 };
	DWORD none = 0;
	if (!owner.compare_exchange_strong(none, GetCurrentThreadId())) {
		if (owner == GetCurrentThreadId()) TerminateProcess(GetCurrentProcess(), 4);
		Sleep(INFINITE);
	}
	{
		CreateDirectoryA(crashDir, nullptr);
		// give the async log thread a moment to write out what led here; no FlushLogs(), its lock may be
		// held by the crashing thread
		Sleep(300);

		char stamp[32];
		time_t now = time(nullptr);
		tm lt {};
		localtime_s(&lt, &now);
		strftime(stamp, sizeof(stamp), "%Y%m%d-%H%M%S", &lt);

		char txtPath[MAX_PATH], dmpPath[MAX_PATH], lastPath[MAX_PATH];
		snprintf(txtPath, MAX_PATH, "%s\\crash-%s.txt", crashDir, stamp);
		snprintf(dmpPath, MAX_PATH, "%s\\crash-%s.dmp", crashDir, stamp);
		snprintf(lastPath, MAX_PATH, "%s\\last_crash.txt", crashDir);

		FILE* f = nullptr;
		fopen_s(&f, txtPath, "w");
		Out(f, "\n=== GemRB crash: %s ===\n", reason);
		if (ep) {
			Out(f, "exception 0x%08lx at %p\n", ep->ExceptionRecord->ExceptionCode, ep->ExceptionRecord->ExceptionAddress);
			if (ep->ExceptionRecord->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && ep->ExceptionRecord->NumberParameters >= 2) {
				Out(f, "%s address 0x%llx\n", ep->ExceptionRecord->ExceptionInformation[0] ? "writing" : "reading",
				    (unsigned long long) ep->ExceptionRecord->ExceptionInformation[1]);
			}
		}
		Out(f, "thread %lu, stack:\n", GetCurrentThreadId());

		if (ep) {
			WriteStack(f, *ep->ContextRecord);
		} else {
			WriteCurrentStack(f);
		}
		Out(f, "minidump: %s\nlog: gemrb.log\n", dmpPath);
		if (f) fclose(f);
		CopyFileA(txtPath, lastPath, FALSE);

		HANDLE dmp = CreateFileA(dmpPath, GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
		if (dmp != INVALID_HANDLE_VALUE) {
			MINIDUMP_EXCEPTION_INFORMATION mei { GetCurrentThreadId(), ep, FALSE };
			MiniDumpWriteDump(GetCurrentProcess(), GetCurrentProcessId(), dmp,
					  MINIDUMP_TYPE(MiniDumpWithIndirectlyReferencedMemory | MiniDumpWithThreadInfo),
					  ep ? &mei : nullptr, nullptr, nullptr);
			CloseHandle(dmp);
		}
		if (_fileno(stderr) >= 0) fflush(stderr);
	}
}

LONG WINAPI OnUnhandled(EXCEPTION_POINTERS* ep)
{
	Report("unhandled exception", ep);
	return EXCEPTION_EXECUTE_HANDLER;
}

void OnAbort(int)
{
	Report("abort (failed assert or fatal error)", nullptr);
	TerminateProcess(GetCurrentProcess(), 3);
}

void OnTerminate()
{
	const char* what = "std::terminate";
	static char buf[512];
	if (auto ex = std::current_exception()) {
		try {
			std::rethrow_exception(ex);
		} catch (const std::exception& e) {
			snprintf(buf, sizeof(buf), "uncaught exception: %s", e.what());
			what = buf;
		} catch (...) {
			what = "uncaught non-std exception";
		}
	}
	Report(what, nullptr);
	TerminateProcess(GetCurrentProcess(), 3);
}

void OnInvalidParameter(const wchar_t*, const wchar_t*, const wchar_t*, unsigned, uintptr_t)
{
	Report("CRT invalid parameter", nullptr);
	TerminateProcess(GetCurrentProcess(), 3);
}

void OnPureCall()
{
	Report("pure virtual call", nullptr);
	TerminateProcess(GetCurrentProcess(), 3);
}

}

// --- hang watchdog ---

BOOL CALLBACK FindOwnWindow(HWND hwnd, LPARAM lp)
{
	DWORD pid = 0;
	GetWindowThreadProcessId(hwnd, &pid);
	if (pid == GetCurrentProcessId() && IsWindowVisible(hwnd)) {
		*reinterpret_cast<HWND*>(lp) = hwnd;
		return FALSE;
	}
	return TRUE;
}

void ReportHang(int seconds)
{
	if (SuspendThread(mainThread) == DWORD(-1)) return;
	CONTEXT ctx {};
	ctx.ContextFlags = CONTEXT_FULL;
	bool haveCtx = GetThreadContext(mainThread, &ctx);

	char stamp[32];
	time_t now = time(nullptr);
	tm lt {};
	localtime_s(&lt, &now);
	strftime(stamp, sizeof(stamp), "%Y%m%d-%H%M%S", &lt);
	char txtPath[MAX_PATH], lastPath[MAX_PATH];
	CreateDirectoryA(crashDir, nullptr);
	snprintf(txtPath, MAX_PATH, "%s\\hang-%s.txt", crashDir, stamp);
	snprintf(lastPath, MAX_PATH, "%s\\last_hang.txt", crashDir);
	FILE* f = nullptr;
	fopen_s(&f, txtPath, "w");
	Out(f, "\n=== GemRB hang: the window hasn't answered for %d s ===\nmain thread stack:\n", seconds);
	if (haveCtx) WriteStack(f, ctx, mainThread);
	if (f) fclose(f);
	ResumeThread(mainThread);
	CopyFileA(txtPath, lastPath, FALSE);
}

DWORD WINAPI Watchdog(LPVOID)
{
	constexpr int CHECK_MS = 2000;
	constexpr int HANG_AFTER = 30; // seconds without an answer (first use of upscaled spell art blocks ~10 s)
	int silent = 0;
	bool reported = false;
	while (true) {
		Sleep(CHECK_MS);
		HWND hwnd = nullptr;
		EnumWindows(FindOwnWindow, reinterpret_cast<LPARAM>(&hwnd));
		if (!hwnd) continue; // not up yet (or a fullscreen switch)
		DWORD_PTR result = 0;
		if (SendMessageTimeoutA(hwnd, WM_NULL, 0, 0, SMTO_ABORTIFHUNG | SMTO_BLOCK, CHECK_MS, &result)) {
			silent = 0;
			reported = false;
			continue;
		}
		silent += CHECK_MS * 2 / 1000;
		if (silent >= HANG_AFTER && !reported) {
			ReportHang(silent);
			reported = true;
		}
	}
	return 0;
}

void InstallCrashHandler()
{
	GetCurrentDirectoryA(MAX_PATH, crashDir);
	strncat_s(crashDir, "\\crashes", _TRUNCATE);

	SetUnhandledExceptionFilter(OnUnhandled);
	signal(SIGABRT, OnAbort);
	_set_abort_behavior(0, _WRITE_ABORT_MSG | _CALL_REPORTFAULT);
	std::set_terminate(OnTerminate);
	_set_invalid_parameter_handler(OnInvalidParameter);
	_set_purecall_handler(OnPureCall);
	// keep a little stack around so a stack overflow can still be reported
	ULONG guarantee = 64 * 1024;
	SetThreadStackGuarantee(&guarantee);

	DuplicateHandle(GetCurrentProcess(), GetCurrentThread(), GetCurrentProcess(), &mainThread,
			THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, 0);
	if (mainThread) CreateThread(nullptr, 0, Watchdog, nullptr, 0, nullptr);
}
