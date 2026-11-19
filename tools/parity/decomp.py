# Decompile named functions (env DECOMP = ;-separated substrings of demangled names) to dump/dec/<name>.c
import idautils, idc, ida_auto, ida_hexrays, os, re
ida_auto.auto_wait(); ida_hexrays.init_hexrays_plugin()
out = os.path.join(os.path.dirname(idc.get_idb_path()), "dump", "dec"); os.makedirs(out, exist_ok=True)
want = [w for w in open(os.path.join(os.path.dirname(idc.get_idb_path()), "decomp_list.txt")).read().splitlines() if w.strip()]
log = open(os.path.join(out, "_log.txt"), "a")
for ea in idautils.Functions():
    n = idc.get_func_name(ea); d = idc.demangle_name(n, idc.get_inf_attr(idc.INF_SHORT_DN)) or n
    for w in want:
        if (w.endswith("$") and d == w[:-1]) or (not w.endswith("$") and w in d):
            fn = re.sub(r"[^A-Za-z0-9_]+", "_", d)[:120] + ".c"
            try:
                c = str(ida_hexrays.decompile(ea))
                open(os.path.join(out, fn), "w", encoding="utf-8").write("// %X %s\n%s" % (ea, d, c))
                log.write("ok %s\n" % d)
            except Exception as e:
                log.write("fail %s %s\n" % (d, e))
            break
log.close(); idc.qexit(0)
