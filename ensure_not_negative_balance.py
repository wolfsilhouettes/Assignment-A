# from selenium import webdriver
# from selenium.webdriver.common.by import By
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC

# driver = webdriver.Chrome()

# # Assuming you've already logged in...
# driver.get("https://parabank.parasoft.com/parabank/overview.htm")

# # Find the username and password input fields and fill them
# username_input = driver.find_element(By.NAME, "username")
# username_input.send_keys("wolfsilhouettes")
# password_input = driver.find_element(By.NAME, "password")
# password_input.send_keys("Batpug1921!") # hash this and store elsewhere

# # Find the login button and click it
# login_button = driver.find_element(By.XPATH, "//input[@value='Log In']")
# login_button.click()

# # Find account 17895
# account = WebDriverWait(driver, 10).until(
#     EC.element_to_be_clickable(
#         (By.LINK_TEXT, "17895")
#     )
# )

# account.click()

# balance_elements = driver.find_elements(
#     By.XPATH,
#     "//*[contains(text(), 'Balance:')]"
# )

# for element in balance_elements:
#     print("TAG:", element.tag_name)
#     print("TEXT:", repr(element.text))
#     print("HTML:", element.get_attribute("outerHTML"))
#     print("------------------------")

# balance = driver.find_element(
#     By.XPATH,
#     "//td[normalize-space()='Balance:']/following-sibling::td[1]"
# )

# print(f"Account 17895 balance: {balance.text}")

# def confirm_if_negative_balance(balance_text: str) -> bool:
#     # Check if the balance is negative
#     if balance_text.startswith('-'):
#         return True
    
#     return False