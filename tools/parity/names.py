import idautils, idc, ida_auto, os
ida_auto.auto_wait()
out = os.path.join(os.path.dirname(idc.get_idb_path()), "dump", "names.txt")
with open(out, "w") as f:
    for ea, n in idautils.Names():
        f.write("%X\t%s\t%s\n" % (ea, n, idc.demangle_name(n, idc.get_inf_attr(idc.INF_SHORT_DN)) or n))
idc.qexit(0)
