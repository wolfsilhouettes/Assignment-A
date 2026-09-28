import winreg
from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver

# AI Generated
# This script detects the default browser on a Windows system to determine how to launch a Selenium WebDriver instance. This allows the
    # script to adapt to the user's preferred browser, whether it's Chrome, Edge, or Firefox. It retrieves the default browser's ProgId 
    # from the Windows registry and initializes the corresponding WebDriver. If the default browser is not supported, it raises an error.
# SUPPORTS: CHROME, EDGE, FIREFOX

def get_default_browser(registry_path: str) -> str:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            registry_path
        )

        prog_id, _ = winreg.QueryValueEx(key, "ProgId")
        winreg.CloseKey(key)

        return prog_id

    except Exception:
        return ""


def create_driver(registry_path: str) -> WebDriver:
    browser = get_default_browser(registry_path)

    print(f"Detected browser: {browser}")

    if browser and "Chrome" in browser:
        return webdriver.Chrome()

    elif browser and ("Edge" in browser or "MSEdge" in browser):
        return webdriver.Edge()

    elif browser and "Firefox" in browser:
        return webdriver.Firefox()

    else:
        # Raise an error to stop the code locally
        raise RuntimeError(
            "[CODE ERROR] Browser type unsupported by application."
        )