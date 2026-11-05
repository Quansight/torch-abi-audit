/* Mark fixture entry points so the linker keeps them, and their references.

   MSVC drops unreferenced internal functions at /O2, which silently erased the
   libtorch calls these fixtures exist to exercise — leaving a DLL that imports
   nothing from torch. The attribute must come *after* ``extern "C"``: placed
   before it, MSVC ignores it without a warning and no export is emitted. */
#ifndef FIXTURE_EXPORT_H
#define FIXTURE_EXPORT_H

#if defined(_WIN32)
#define FIXTURE_EXPORT __declspec(dllexport)
#else
#define FIXTURE_EXPORT __attribute__((visibility("default")))
#endif

#endif /* FIXTURE_EXPORT_H */
