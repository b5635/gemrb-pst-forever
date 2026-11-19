import idc, ida_auto, idautils, ida_funcs, os
ida_auto.auto_wait()
base = os.path.dirname(idc.get_idb_path())
with open(os.path.join(base, "dump", "xrefs.txt"), "w") as f:
    for l in open(os.path.join(base, "xref_ea.txt")).read().split():
        ea = int(l, 16)
        for x in idautils.CodeRefsTo(ea, 0):
            fn = ida_funcs.get_func(x)
            f.write("%X <- %X %s size=%d\n" % (ea, x, idc.get_func_name(x), fn.size() if fn else 0))
idc.qexit(0)
