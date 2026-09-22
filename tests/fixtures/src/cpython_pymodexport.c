/* Python 3.15 extension exporting only the PEP 793 hook, with no PyInit_. */
#include <Python.h>

PyABIInfo_VAR(abi_info);

static PySlot slots[] = {
    PySlot_DATA(Py_mod_abi, &abi_info),
    PySlot_DATA(Py_mod_name, "fixture_pymodexport"),
    PySlot_END
};

PyMODEXPORT_FUNC PyModExport_fixture_pymodexport(void) {
    return slots;
}
