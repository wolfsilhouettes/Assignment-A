from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

# AI generated
# Intent of code: create a reusable function that searches for intended elements on a webpage based on their purpose (e.g., username, password, login, transfer). 
# The function uses a dictionary of selectors for each purpose and iterates through them to find the first matching element. 
# If no element is found for the specified purpose, it raises an error.
# This would ensure the code could apply to different websites with similar functionality without hardcoding specific selectors.

def find_element_by_purpose(
    driver: WebDriver,
    purpose: str
) -> WebElement:

    purpose = purpose.lower().strip()

    selectors = {
        "username": [
            (By.NAME, "username"),
            (By.ID, "username"),
            (By.NAME, "user"),
            (By.ID, "user"),
            (By.NAME, "login"),
            (By.ID, "login"),
            (
                By.XPATH,
                "//input[contains(translate(@placeholder, "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'username')]"
            ),
            (
                By.XPATH,
                "//input[contains(translate(@aria-label, "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'username')]"
            ),
        ],

        "password": [
            (By.NAME, "password"),
            (By.ID, "password"),
            (By.XPATH, "//input[@type='password']"),
            (
                By.XPATH,
                "//input[contains(translate(@placeholder, "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'password')]"
            ),
            (
                By.XPATH,
                "//input[contains(translate(@aria-label, "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'password')]"
            ),
        ],

        "login": [
            (
                By.XPATH,
                "//button[contains(translate(normalize-space(), "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'login')]"
            ),
            (
                By.XPATH,
                "//input[contains(translate(@value, "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'login')]"
            ),
            (
                By.XPATH,
                "//a[contains(translate(normalize-space(), "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'login')]"
            ),
        ],

        "transfer": [
            (By.LINK_TEXT, "Transfer Funds"),
            (
                By.XPATH,
                "//a[contains(normalize-space(), 'Transfer')]"
            ),
            (
                By.XPATH,
                "//button[contains(normalize-space(), 'Transfer')]"
            ),
        ],
        "logout": [
            # Link
            (
                By.XPATH,
                "//a[contains(translate(normalize-space(), "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'log out')]"
            ),

            # Button
            (
                By.XPATH,
                "//button[contains(translate(normalize-space(), "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'log out')]"
            ),

            # Input button, e.g. <input value="Log Out">
            (
                By.XPATH,
                "//input[contains(translate(@value, "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'log out')]"
            ),
        ]
    }

    # -----------------------------
    # Strategy 1: Known selectors
    # -----------------------------

    if purpose in selectors:

        for by, selector in selectors[purpose]:

            elements = driver.find_elements(by, selector)

            if elements:
                return elements[0]

    # -----------------------------
    # Strategy 2: Generic text search -> Too unnecessarily slow
    # -----------------------------

    # keywords = {
    #     "username": [
    #         "username",
    #         "user name",
    #         "member number",
    #         "member id",
    #         "login id"
    #     ],

    #     "password": [
    #         "password",
    #         "passcode"
    #     ],

    #     "login": [
    #         "login",
    #         "log in",
    #         "sign in",
    #         "signin"
    #     ],

    #     "transfer": [
    #         "transfer",
    #         "transfer funds",
    #         "send money"
    #     ],
    #     "logout": [
    #         "logout",
    #         "log out",
    #         "sign out",
    #         "signout"
    #     ],
    # }

    # if purpose in keywords:

    #     for keyword in keywords[purpose]:

    #         try:
    #             return find_by_text(driver, keyword)

    #         except RuntimeError:
    #             continue

    # raise RuntimeError(
    #     f"Could not find an element for purpose: {purpose}"
    # )


# def find_by_text(
#     driver: WebDriver,
#     keyword: str
# ) -> WebElement:

#     keyword = keyword.lower().strip()

#     elements = driver.find_elements(
#         By.CSS_SELECTOR,
#         "a, button, input, select, textarea"
#     )

#     print(f"\n[DEBUG] Searching for: '{keyword}'")
#     print(f"[DEBUG] Found {len(elements)} possible elements")

#     for element in elements:

#         attributes = {
#             "tag": element.tag_name,
#             "text": element.text,
#             "value": element.get_attribute("value"),
#             "aria-label": element.get_attribute("aria-label"),
#             "placeholder": element.get_attribute("placeholder"),
#             "title": element.get_attribute("title"),
#             "name": element.get_attribute("name"),
#             "id": element.get_attribute("id"),
#         }

#         #print("[DEBUG]", attributes)

#         for attribute in attributes.values():

#             if attribute and keyword in str(attribute).lower():
#                 print(
#                     f"[DEBUG] MATCH FOUND: {attributes}"
#                 )
#                 return element

#     raise RuntimeError(
#         f"Could not find an element containing '{keyword}'."
#     )