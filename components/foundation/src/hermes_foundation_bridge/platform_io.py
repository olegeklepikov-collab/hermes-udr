"""Small native file-system primitives shared by the foundation services."""

from __future__ import annotations

import errno
import os
import stat
import time
from pathlib import Path

LOCK_EX = 2
LOCK_NB = 4
LOCK_UN = 8
_IS_WINDOWS = os.name == "nt"
BINARY_FLAG = getattr(os, "O_BINARY", 0)

if _IS_WINDOWS:
    import msvcrt
else:
    import fcntl


def flock(descriptor: int, operation: int) -> None:
    """Advisory whole-writer lock; on Windows lock byte zero with msvcrt."""
    if not _IS_WINDOWS:
        fcntl.flock(descriptor, operation)
        return
    if operation not in (LOCK_EX, LOCK_EX | LOCK_NB, LOCK_UN):
        raise ValueError("unsupported lock operation")
    os.lseek(descriptor, 0, os.SEEK_SET)
    if operation == LOCK_UN:
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    # A region beyond EOF has differing behavior across CRT versions.
    if os.fstat(descriptor).st_size == 0:
        os.write(descriptor, b"\0")
        os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            return
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            if operation & LOCK_NB:
                raise BlockingIOError(errno.EAGAIN, "writer lock held") from error
            time.sleep(0.02)


def sync_directory(path: Path) -> bool:
    """Return whether directory fsync was performed; Windows cannot do it here."""
    if _IS_WINDOWS:
        return False
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return True


def open_read_nofollow(path: Path, *, nonblocking: bool = False) -> int:
    """Open a binary file while rejecting a final symlink/reparse point."""
    if not _IS_WINDOWS:
        return os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | (getattr(os, "O_NONBLOCK", 0) if nonblocking else 0),
        )
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    class FileInfo(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation", FileTime),
            ("access", FileTime),
            ("write", FileTime),
            ("volume", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 0x00000007, None, 3, 0x00200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = FileInfo()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & 0x00000400:
            raise OSError(errno.ELOOP, "reparse point rejected", str(path))
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | BINARY_FLAG)
        handle = None
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise OSError(errno.EINVAL, "regular file required", str(path))
        return descriptor
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)


def private_file(descriptor: int) -> None:
    """Restrict a newly created file, failing closed if Windows ACL setup fails."""
    if not _IS_WINDOWS:
        os.fchmod(descriptor, 0o600)
        return
    _private_windows_handle(msvcrt.get_osfhandle(descriptor), inherit=False)


def private_directory(path: Path) -> None:
    """Restrict a service directory and child ACL inheritance."""
    if not _IS_WINDOWS:
        path.chmod(0o700)
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # SetSecurityInfo may read existing inheritance while replacing the DACL.
    # Match the working file path's WRITE_DAC | READ_CONTROL access request.
    handle = kernel.CreateFileW(str(path), 0x00060000, 0x00000007, None, 3, 0x02200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        _private_windows_handle(handle, inherit=True)
    finally:
        kernel.CloseHandle(handle)


def windows_private_file_allowed(path: Path) -> bool:
    """Check a Windows file's effective DACL against the small trusted SID set."""
    if not _IS_WINDOWS:
        raise RuntimeError("Windows ACL inspection requires Windows")
    import ctypes
    from ctypes import wintypes

    try:
        descriptor = open_read_nofollow(path)
    except OSError:
        return False
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(descriptor))
    token = wintypes.HANDLE()
    security_descriptor = ctypes.c_void_p()
    system_sid = ctypes.c_void_p()
    administrators_sid = ctypes.c_void_p()
    try:
        advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi.OpenProcessToken.restype = wintypes.BOOL
        advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        advapi.GetTokenInformation.restype = wintypes.BOOL
        advapi.GetSecurityInfo.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        advapi.GetSecurityInfo.restype = wintypes.DWORD
        advapi.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
        advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
        advapi.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
        advapi.ConvertStringSidToSidW.restype = wintypes.BOOL
        advapi.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        advapi.EqualSid.restype = wintypes.BOOL
        advapi.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
        advapi.GetAce.restype = wintypes.BOOL
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]

        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            return False
        needed = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        token_info = ctypes.create_string_buffer(needed.value)
        if not advapi.GetTokenInformation(token, 1, token_info, needed, ctypes.byref(needed)):
            return False
        current_sid = ctypes.cast(token_info, ctypes.POINTER(ctypes.c_void_p))[0]
        if not advapi.ConvertStringSidToSidW("S-1-5-18", ctypes.byref(system_sid)):
            return False
        if not advapi.ConvertStringSidToSidW("S-1-5-32-544", ctypes.byref(administrators_sid)):
            return False
        allowed = (current_sid, system_sid, administrators_sid)
        owner = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        result = advapi.GetSecurityInfo(
            handle, 1, 0x00000005, ctypes.byref(owner), None,
            ctypes.byref(dacl), None, ctypes.byref(security_descriptor),
        )
        if result or not owner.value or not dacl.value:
            return False
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if not advapi.GetSecurityDescriptorControl(
            security_descriptor, ctypes.byref(control), ctypes.byref(revision)
        ) or not control.value & 0x1000:
            return False
        if not any(advapi.EqualSid(owner, sid) for sid in allowed):
            return False

        class Acl(ctypes.Structure):
            _fields_ = [
                ("revision", ctypes.c_ubyte), ("reserved", ctypes.c_ubyte),
                ("size", wintypes.WORD), ("ace_count", wintypes.WORD),
                ("reserved2", wintypes.WORD),
            ]

        class AceHeader(ctypes.Structure):
            _fields_ = [
                ("type", ctypes.c_ubyte), ("flags", ctypes.c_ubyte),
                ("size", wintypes.WORD),
            ]

        ace_count = ctypes.cast(dacl, ctypes.POINTER(Acl)).contents.ace_count
        for index in range(ace_count):
            ace = ctypes.c_void_p()
            if not advapi.GetAce(dacl, index, ctypes.byref(ace)) or not ace.value:
                return False
            header = ctypes.cast(ace, ctypes.POINTER(AceHeader)).contents
            if header.type == 1:  # Standard deny ACE can only reduce access.
                continue
            if header.type != 0 or header.size < 16:
                return False
            sid = ctypes.c_void_p(ace.value + 8)
            if not any(advapi.EqualSid(sid, trusted) for trusted in allowed):
                return False
        return True
    finally:
        if security_descriptor.value:
            kernel.LocalFree(security_descriptor)
        if system_sid.value:
            kernel.LocalFree(system_sid)
        if administrators_sid.value:
            kernel.LocalFree(administrators_sid)
        if token.value:
            kernel.CloseHandle(token)
        os.close(descriptor)


def _private_windows_handle(handle: int, *, inherit: bool) -> None:
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    token = wintypes.HANDLE()
    TOKEN_QUERY = 0x0008
    TOKEN_USER = 1
    DACL_SECURITY_INFORMATION = 0x00000004
    PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
    SE_FILE_OBJECT = 1
    ACL_REVISION = 2
    FILE_ALL_ACCESS = 0x001F01FF

    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi.GetLengthSid.restype = wintypes.DWORD
    advapi.InitializeAcl.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
    advapi.InitializeAcl.restype = wintypes.BOOL
    advapi.AddAccessAllowedAceEx.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    advapi.AddAccessAllowedAceEx.restype = wintypes.BOOL
    advapi.SetSecurityInfo.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi.SetSecurityInfo.restype = wintypes.DWORD
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    class FileInfo(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation", FileTime),
            ("access", FileTime),
            ("write", FileTime),
            ("volume", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL

    def identity(file_handle: int) -> tuple[int, int, int]:
        info = FileInfo()
        check(kernel.GetFileInformationByHandle(file_handle, ctypes.byref(info)))
        if info.attributes & 0x00000400:
            raise OSError(errno.ELOOP, "reparse point rejected")
        return info.volume, info.file_index_high, info.file_index_low

    def check(result: int) -> None:
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())

    check(advapi.OpenProcessToken(kernel.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)))
    try:
        needed = wintypes.DWORD()
        advapi.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(needed))
        buffer = ctypes.create_string_buffer(needed.value)
        check(advapi.GetTokenInformation(token, TOKEN_USER, buffer, needed, ctypes.byref(needed)))
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        acl_size = 8 + 8 + advapi.GetLengthSid(sid)
        acl = ctypes.create_string_buffer(acl_size)
        check(advapi.InitializeAcl(acl, acl_size, ACL_REVISION))
        check(advapi.AddAccessAllowedAceEx(acl, ACL_REVISION, 3 if inherit else 0, FILE_ALL_ACCESS, sid))
        flags = DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION
        if inherit:
            result = advapi.SetSecurityInfo(handle, SE_FILE_OBJECT, flags, None, None, acl, None)
        else:
            # CRT descriptors lack WRITE_DAC. Reopen this exact file with that
            # right and reject a replacement or reparse point before setting ACL.
            original_identity = identity(handle)
            length = kernel.GetFinalPathNameByHandleW(handle, None, 0, 0)
            if not length:
                raise ctypes.WinError(ctypes.get_last_error())
            name = ctypes.create_unicode_buffer(length + 1)
            if not kernel.GetFinalPathNameByHandleW(handle, name, length + 1, 0):
                raise ctypes.WinError(ctypes.get_last_error())
            acl_handle = kernel.CreateFileW(name.value, 0x00060000, 0x00000007, None, 3, 0x00200000, None)
            if acl_handle == wintypes.HANDLE(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if identity(acl_handle) != original_identity:
                    raise OSError(errno.ESTALE, "file changed during ACL setup")
                result = advapi.SetSecurityInfo(acl_handle, SE_FILE_OBJECT, flags, None, None, acl, None)
            finally:
                kernel.CloseHandle(acl_handle)
        if result:
            raise OSError(result, "unable to restrict file ACL")
    finally:
        kernel.CloseHandle(token)


def secure_file(path: Path) -> None:
    """Apply the same private file policy to an existing service-owned file."""
    descriptor = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
    try:
        private_file(descriptor)
    finally:
        os.close(descriptor)


def is_private_file(path: Path) -> bool:
    from .native_runtime import assert_private_file
    try:
        assert_private_file(path)
    except (ValueError, OSError):
        return False
    return True
