import sys

# Win32 错误码
_ERROR_ACCESS_DENIED = 5
_ERROR_ALREADY_EXISTS = 183

_mutex_handle = None


def acquire_single_instance(name: str) -> bool:
    """
    通过命名互斥量保证只有一个实例在运行，成功获得返回 True，已有实例在运行返回 False
    互斥量随进程退出（包括崩溃）自动释放，不会像锁文件那样残留。
    非 Windows 平台不做限制。
    """
    global _mutex_handle
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, name)
        err = ctypes.get_last_error()
        if not handle:
            # 管理员权限的实例创建的互斥量，普通权限的实例打开时会被拒绝访问，同样说明已有实例在运行
            return err != _ERROR_ACCESS_DENIED
        if err == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle(handle)
            return False
        _mutex_handle = handle   # 保持句柄直到进程退出
        return True
    except Exception:
        return True     # 检测本身出错时不阻止程序启动
