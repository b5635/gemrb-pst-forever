import idc, ida_auto, ida_hexrays, os
ida_auto.auto_wait(); ida_hexrays.init_hexrays_plugin()
base = os.path.dirname(idc.get_idb_path())
out = os.path.join(base, "dump", "dec"); os.makedirs(out, exist_ok=True)
for l in open(os.path.join(base, "decomp_ea.txt")).read().split():
    ea = int(l, 16)
    try:
        c = str(ida_hexrays.decompile(ea)); open(os.path.join(out, "%X.c" % ea), "w", encoding="utf-8").write(c)
    except Exception as e:
        open(os.path.join(out, "%X.err" % ea), "w").write(str(e))
idc.qexit(0)
