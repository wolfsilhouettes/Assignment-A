from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json
import utils.json_retrieval
from src.launch_via_default_browser import create_driver
from src.find_specific_field import find_element_by_purpose
from src.verify_log_in import verify_logged_in
from workflow_replay import WorkflowReplay

def main():
    # Retrieve the default configurations from the config.json file
    inputs = utils.json_retrieval.load_json_file("config/config.json")
    file_paths = utils.json_retrieval.load_json_file("config/paths.json")

    # Initialize the username, password, and website URL from the config file
    username = inputs.get("username")
    password = inputs.get("password")
    website_url = inputs.get("website")
    registry_path = file_paths.get("registry_path")

    # Validate that the configuration file inputs are not empty
    if not username or not password or not website_url or not registry_path:
        raise ValueError("[ERROR WITH ASSIGNMENT A] Username, password, website URL, and registry path must be provided in the config.json file.")

    # Find the default browser the user's computer is using and create a driver for it
    try:
        driver = create_driver(registry_path)
        print("[INFO] Successfully created a WebDriver instance for the default browser.")
    except RuntimeError as e:
        raise RuntimeError("[ERROR WITH ASSIGNMENT A] Could not create a WebDriver instance for the default browser. Please ensure that the default browser is supported (Chrome, Edge, or Firefox).") from e

    # Verify that the website provided exists
    try: 
        driver.get(website_url)
        print(f"[INFO] Successfully accessed the website: {website_url}")
    except Exception as e:
        raise ConnectionError(f"[ERROR WITH ASSIGNMENT A] Unable to access the website: {website_url}. Please check the URL and your internet connection.") from e

    # Log into the account using the provided username and password
    verify_logged_in(driver, username, password)

    # Run the workflow steps from the inputs.json file
    my_steps = utils.json_retrieval.load_json_file("config/inputs.json")

    # Use the workflow id name to determine what the user wants to do
    replay = WorkflowReplay(driver)

    # Retrieve the inputs from the inputs.json file
    inputs = my_steps.get("inputs", {})
    #print(f"[INFO] Retrieved inputs from inputs.json: {inputs}")

    replay.run(
            my_steps,
            inputs
        )

    # driver.quit()


if __name__ == "__main__":
    main()









