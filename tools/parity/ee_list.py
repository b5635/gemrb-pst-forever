import idautils, idc, ida_auto, ida_funcs, os, re
ida_auto.auto_wait()
out = os.path.join(os.path.dirname(idc.get_idb_path()), "dump"); os.makedirs(out, exist_ok=True)
with open(os.path.join(out, "funcs.txt"), "w") as f:
    for ea in idautils.Functions():
        n = idc.get_func_name(ea)
        d = idc.demangle_name(n, idc.get_inf_attr(idc.INF_SHORT_DN)) or n
        f.write("%X\t%d\t%s\n" % (ea, ida_funcs.get_func(ea).size(), d))
import ida_hexrays
f2 = open(os.path.join(out, "hexrays.txt"), "w"); f2.write(str(ida_hexrays.init_hexrays_plugin())); f2.close()
idc.qexit(0)
