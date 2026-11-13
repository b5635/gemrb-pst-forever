// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#ifndef GEMRB_WIN_CRASHHANDLER_H
#define GEMRB_WIN_CRASHHANDLER_H

// writes crashes\crash-<time>.txt (symbolized stack) and a .dmp on any crash, relative to the working dir
void InstallCrashHandler();

#endif
