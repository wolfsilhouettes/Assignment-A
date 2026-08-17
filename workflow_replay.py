import json

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


class WorkflowReplay:

    def __init__(self, driver: WebDriver):
        self.driver = driver

    def replace_variables(self, value: str, inputs: dict):

        for key, replacement in inputs.items():

            value = value.replace(
                "{{" + key + "}}",
                str(replacement)
            )

        return value

    def find_target(self, target):

        strategy = target["strategy"]
        value = target["value"]

        strategies = {
            "id": By.ID,
            "name": By.NAME,
            "xpath": By.XPATH,
            "link_text": By.LINK_TEXT,
            "partial_link_text": By.PARTIAL_LINK_TEXT,
            "css": By.CSS_SELECTOR,
            "tag": By.TAG_NAME,
        }

        if strategy not in strategies:
            raise ValueError(
                f"Unsupported targeting strategy: {strategy}"
            )

        locator = (
            strategies[strategy],
            value
        )

        while True:

            try:

                # Give the application 10 seconds
                # to find the element
                return WebDriverWait(
                    self.driver,
                    10
                ).until(
                    EC.presence_of_element_located(locator)
                )

            except TimeoutException:

                print("\n===================================")
                print("[WARNING] Element could not be found.")
                print("===================================")

                print(f"Strategy: {strategy}")
                print(f"Value: {value}")
                print(f"Current URL: {self.driver.current_url}")
                print(f"Page title: {self.driver.title}")

                try:

                    page_text = self.driver.find_element(
                        By.TAG_NAME,
                        "body"
                    ).text

                    print("\nVisible page text:")
                    print(page_text[:5000])

                except Exception:

                    print(
                        "[WARNING] Could not retrieve page text."
                    )

                try:

                    self.driver.save_screenshot(
                        "debug_timeout.png"
                    )

                    print(
                        "\n[DEBUG] Screenshot saved as "
                        "debug_timeout.png"
                    )

                except Exception:

                    print(
                        "[WARNING] Could not save screenshot."
                    )

                # -----------------------------------------
                # Pause for human intervention
                # -----------------------------------------

                input(
                    "\n[PAUSED] Fix the application if necessary, "
                    "then press Enter to retry..."
                )

                print(
                    f"\n[INFO] Retrying target: "
                    f"{strategy} = {value}"
                )

                # The while loop starts over here.

    def execute_step(self, step, inputs):

        action = step["action"]

        print(f"[DEBUG] Action: {action}")
        print(f"[DEBUG] Target: {step['target']}")

        target = self.find_target(
            step["target"]
        )

        print(
            f"[DEBUG] Found element: "
            f"tag={target.tag_name}, "
            f"text={repr(target.text)}, "
            f"type={target.get_attribute('type')}"
        )

        if action == "click":

            print("[DEBUG] Clicking element...")
            target.click()

        elif action == "input":

            value = self.replace_variables(
                step["value"],
                inputs
            )

            print(f"[DEBUG] Input value: {value}")

            target.clear()
            target.send_keys(value)

        elif action == "select":

            value = self.replace_variables(
                step["value"],
                inputs
            )

            print(f"[DEBUG] Selecting value: {value}")

            from selenium.webdriver.support.ui import Select

            select_element = Select(target)
            select_element.select_by_visible_text(value)

        else:

            raise ValueError(
                f"Unsupported action: {action}"
            )

    def run(self, workflow: dict, inputs: dict):

        print(
            f"Running workflow: "
            f"{workflow['workflow_id']} "
            f"v{workflow['version']}"
        )

        for number, step in enumerate(
            workflow["steps"],
            start=1
        ):

            print(
                f"Executing step {number}: "
                f"{step['action']}"
            )

            self.execute_step(
                step,
                inputs
            )

        print("Workflow completed successfully.")