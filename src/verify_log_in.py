
from src.find_specific_field import find_element_by_purpose
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

# Track whether the user is logged in to maximize reuse.
def verify_logged_in(driver: WebDriver, username: str, password: str) -> None:
    """
    Verify if the user is logged in by checking for the presence of a logout button or a specific element that indicates a successful login.
    
    Args:
        driver (WebDriver): The Selenium WebDriver instance.
        username (str): The username for the account.
        password (str): The password for the account.
    """

    # Verify if the user is already logged into their profile -> look for log out link/button
    # Early guard for if the script needs to rerun
    # try:
    #     logout_button = find_element_by_purpose(
    #         driver,
    #         "logout"
    #     )

    #     print("[INFO] User is logged in.")
    #     return True

    # except RuntimeError:
    #     print("[INFO] User is not currently logged in.")

    # Verify that the login button exists
    login_button = find_element_by_purpose(driver, "login")
    if not login_button:
        return
    else:
        # Fill the login form with the provided username and password
        fill_login_form(driver, username, password, login_button)


def fill_login_form(
        driver: WebDriver,
        username: str, 
        password: str, 
        login_button: WebElement) -> None:
    """
    Fill the login form with the provided username and password.
    
    Args:
        driver (WebDriver): The Selenium WebDriver instance.
        username (str): The username for the account.
        password (str): The password for the account.
    """
    # Log into the account using the provided username and password
    username_field = find_element_by_purpose(driver, "username")
    if username_field:
        username_field.send_keys(username)
    else:
        raise RuntimeError("[ERROR WITH ASSIGNMENT A] Could not find the username input field on the webpage.")

    password_field = find_element_by_purpose(driver, "password")
    if password_field:
        password_field.send_keys(password)
    else:
        raise RuntimeError("[ERROR WITH ASSIGNMENT A] Could not find the password input field on the webpage.")

    if login_button:
        login_button.click()
    else:
        raise RuntimeError("[ERROR WITH ASSIGNMENT A] Could not find the login button on the webpage.")