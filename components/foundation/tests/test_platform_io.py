from __future__ import annotations

import errno
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hermes_foundation_bridge import platform_io


class PlatformIOTests(unittest.TestCase):
    def test_read_rejects_final_symlink(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX branch")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            target.write_bytes(b"secret\r\nbytes")
            descriptor = platform_io.open_read_nofollow(target)
            try:
                self.assertEqual(os.read(descriptor, 100), b"secret\r\nbytes")
            finally:
                os.close(descriptor)
            link = Path(directory) / "link"
            link.symlink_to(target)
            with self.assertRaises(OSError):
                platform_io.open_read_nofollow(link)

    def test_posix_lock_excludes_second_descriptor(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX branch")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "writer.lock"
            first = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            second = os.open(path, os.O_RDWR)
            try:
                platform_io.flock(first, platform_io.LOCK_EX)
                with self.assertRaises(BlockingIOError):
                    platform_io.flock(
                        second, platform_io.LOCK_EX | platform_io.LOCK_NB
                    )
                platform_io.flock(first, platform_io.LOCK_UN)
                platform_io.flock(second, platform_io.LOCK_EX | platform_io.LOCK_NB)
                platform_io.flock(second, platform_io.LOCK_UN)
            finally:
                os.close(second)
                os.close(first)

    def test_windows_branch_uses_real_locking_api_and_reports_contention(self) -> None:
        # This exercises dispatch only; it does not qualify Windows behavior.
        calls = []
        held = False

        def locking(descriptor: int, operation: int, length: int) -> None:
            nonlocal held
            calls.append((operation, length))
            if operation == 2:
                if held:
                    raise OSError(errno.EACCES, "held")
                held = True
            else:
                held = False

        fake = SimpleNamespace(locking=locking, LK_NBLCK=2, LK_UNLCK=0)
        with tempfile.TemporaryDirectory() as directory:
            descriptor = os.open(Path(directory) / "lock", os.O_CREAT | os.O_RDWR)
            try:
                with patch.object(platform_io, "_IS_WINDOWS", True), patch.object(
                    platform_io, "msvcrt", fake, create=True
                ):
                    platform_io.flock(descriptor, platform_io.LOCK_EX)
                    with self.assertRaises(BlockingIOError):
                        platform_io.flock(
                            descriptor, platform_io.LOCK_EX | platform_io.LOCK_NB
                        )
                    platform_io.flock(descriptor, platform_io.LOCK_UN)
                    self.assertFalse(platform_io.sync_directory(Path(directory)))
            finally:
                os.close(descriptor)
        self.assertEqual(calls, [(2, 1), (2, 1), (0, 1)])

    def test_windows_private_file_fails_closed_on_acl_error(self) -> None:
        fake = SimpleNamespace(get_osfhandle=lambda descriptor: descriptor)
        with patch.object(platform_io, "_IS_WINDOWS", True), patch.object(
            platform_io, "msvcrt", fake, create=True
        ), patch.object(
            platform_io, "_private_windows_handle", side_effect=OSError("ACL denied")
        ):
            with self.assertRaisesRegex(OSError, "ACL denied"):
                platform_io.private_file(7)

    @unittest.skipUnless(os.name == "nt", "requires a real Windows host")
    def test_windows_private_directory_sets_protected_acl(self) -> None:
        import ctypes
        from ctypes import wintypes

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "restricted"
            path.mkdir()
            platform_io.private_directory(path)
            advapi = ctypes.WinDLL("advapi32", use_last_error=True)
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            security_descriptor = ctypes.c_void_p()
            dacl = ctypes.c_void_p()
            advapi.GetNamedSecurityInfoW.argtypes = [
                wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
            self.assertEqual(advapi.GetNamedSecurityInfoW(
                str(path), 1, 0x4, None, None, ctypes.byref(dacl), None,
                ctypes.byref(security_descriptor),
            ), 0)
            try:
                control = wintypes.WORD()
                revision = wintypes.DWORD()
                advapi.GetSecurityDescriptorControl.argtypes = [
                    ctypes.c_void_p, ctypes.POINTER(wintypes.WORD),
                    ctypes.POINTER(wintypes.DWORD),
                ]
                advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
                self.assertTrue(advapi.GetSecurityDescriptorControl(
                    security_descriptor, ctypes.byref(control), ctypes.byref(revision)
                ))
                self.assertTrue(control.value & 0x1000)
                self.assertTrue(dacl.value)
            finally:
                kernel.LocalFree.argtypes = [ctypes.c_void_p]
                kernel.LocalFree(security_descriptor)

    @unittest.skipUnless(os.name == "nt", "requires a real Windows host")
    def test_windows_private_file_sets_protected_single_entry_acl(self) -> None:
        import ctypes
        from ctypes import wintypes

        descriptor, name = tempfile.mkstemp()
        try:
            platform_io.private_file(descriptor)
            self.assertTrue(platform_io.windows_private_file_allowed(Path(name)))
            advapi = ctypes.WinDLL("advapi32", use_last_error=True)
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            security_descriptor = ctypes.c_void_p()
            dacl = ctypes.c_void_p()
            advapi.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
            result = advapi.GetNamedSecurityInfoW(
                name, 1, 0x4, None, None, ctypes.byref(dacl), None,
                ctypes.byref(security_descriptor),
            )
            self.assertEqual(result, 0)
            try:
                control = wintypes.WORD()
                revision = wintypes.DWORD()
                advapi.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
                advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
                self.assertTrue(advapi.GetSecurityDescriptorControl(
                    security_descriptor, ctypes.byref(control), ctypes.byref(revision)
                ))
                self.assertTrue(control.value & 0x1000)  # SE_DACL_PROTECTED

                class AclSizeInfo(ctypes.Structure):
                    _fields_ = [("ace_count", wintypes.DWORD), ("bytes_in_use", wintypes.DWORD), ("bytes_free", wintypes.DWORD)]

                size = AclSizeInfo()
                advapi.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
                advapi.GetAclInformation.restype = wintypes.BOOL
                self.assertTrue(advapi.GetAclInformation(
                    dacl, ctypes.byref(size), ctypes.sizeof(size), 2
                ))
                self.assertEqual(size.ace_count, 1)
            finally:
                kernel.LocalFree.argtypes = [ctypes.c_void_p]
                kernel.LocalFree(security_descriptor)
        finally:
            os.close(descriptor)
            Path(name).unlink(missing_ok=True)

    @unittest.skipUnless(os.name == "nt", "requires a real Windows host")
    def test_windows_private_file_rejects_everyone_allow_ace(self) -> None:
        import ctypes
        from ctypes import wintypes

        descriptor, name = tempfile.mkstemp()
        try:
            platform_io.private_file(descriptor)
            advapi = ctypes.WinDLL("advapi32", use_last_error=True)
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            everyone = ctypes.c_void_p()
            advapi.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
            advapi.ConvertStringSidToSidW.restype = wintypes.BOOL
            self.assertTrue(advapi.ConvertStringSidToSidW("S-1-1-0", ctypes.byref(everyone)))
            try:
                advapi.GetLengthSid.argtypes = [ctypes.c_void_p]
                advapi.GetLengthSid.restype = wintypes.DWORD
                acl = ctypes.create_string_buffer(16 + advapi.GetLengthSid(everyone))
                advapi.InitializeAcl.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
                advapi.InitializeAcl.restype = wintypes.BOOL
                advapi.AddAccessAllowedAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
                advapi.AddAccessAllowedAce.restype = wintypes.BOOL
                self.assertTrue(advapi.InitializeAcl(acl, len(acl), 2))
                self.assertTrue(advapi.AddAccessAllowedAce(acl, 2, 0x001F01FF, everyone))

                kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
                kernel.CreateFileW.restype = wintypes.HANDLE
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                acl_handle = kernel.CreateFileW(name, 0x00060000, 7, None, 3, 0x00200000, None)
                self.assertNotEqual(acl_handle, wintypes.HANDLE(-1).value)
                try:
                    advapi.SetSecurityInfo.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
                    advapi.SetSecurityInfo.restype = wintypes.DWORD
                    self.assertEqual(advapi.SetSecurityInfo(
                        acl_handle, 1, 0x80000004, None, None, acl, None
                    ), 0)
                finally:
                    kernel.CloseHandle(acl_handle)
                self.assertFalse(platform_io.windows_private_file_allowed(Path(name)))
            finally:
                kernel.LocalFree.argtypes = [ctypes.c_void_p]
                kernel.LocalFree(everyone)
        finally:
            os.close(descriptor)
            Path(name).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
