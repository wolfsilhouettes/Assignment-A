import webbrowser
from selenium import webdriver
from selenium.webdriver.common.by import By

# Initialize the WebDriver
driver = webdriver.Chrome()

# Navigate to the URL
driver.get("https://parabank.parasoft.com/parabank/overview.htm")

# Find the username and password input fields and fill them
username_input = driver.find_element(By.NAME, "username")
username_input.send_keys("wolfsilhouettes")
password_input = driver.find_element(By.NAME, "password")
password_input.send_keys("Batpug1921!")

# Find the login button and click it
login_button = driver.find_element(By.XPATH, "//input[@value='Log In']")
login_button.click()

# Print the url of the current page after log in
print(driver.current_url)

# TARGET A: Find a link by its text label
transfer_link = driver.find_element(
    By.XPATH,
    "//a[contains(normalize-space(), 'Transfer Funds')]"
)

transfer_url = transfer_link.get_attribute("href")

print(f"URL 2: {transfer_url}")

driver.find_element(By.LINK_TEXT, "Transfer Funds").click() 
print(driver.current_url)

# Locate the amount textbox and fill it with the amount to transfer
amount_input = driver.find_element(By.ID, "amount")
amount_input.send_keys("200")

# Fill in the account inputbox with a fake account
from_account = driver.find_element(By.ID, "fromAccountId")
from_account.send_keys("17784")

# Fill in the to account inputbox with a fake account
to_account = driver.find_element(By.ID, "toAccountId")
to_account.send_keys("17895")

# Click the transfer button
transfer_button = driver.find_element(By.XPATH, "//input[@value='Transfer']")
transfer_button.click()

# Ensure the transfer complete screen appears by locating the Transfer Complete header
is_successful = driver.find_element(By.XPATH, "//h1[contains(normalize-space(), 'Transfer Complete')]")
if is_successful:
    print("Transfer completed successfully.")

