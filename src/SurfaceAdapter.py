from selenium.webdriver.support.ui import Select
from src.find_specific_field import find_element_by_purpose
from selenium.webdriver.common.by import By
from src.exceptions import ElementNotFoundError
from typing import Callable, Optional
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import InvalidSelectorException, TimeoutException
import re

class SurfaceAdapter():
    def __init__(self, driver):
        self.driver = driver

    def observe(self) -> dict:
        return {
            "url": self.driver.current_url,
            "title": self.driver.title,
            "visible_text": self.driver.find_element(
                By.TAG_NAME,
                "body"
            ).text,
        }

    def locate(self, target: dict, action: str):
        selector = target.get("selector")
        named_element = target.get("element_name")
        if not selector and named_element:
            selectors = [
                f"#{named_element}",
                f"[name='{named_element}']",
            ]
        else:
            selectors = [selector] if selector else []
        if selectors:
            if selector and "transfer.htm" in selector:
                selectors.extend([
                    "a[href*='transfer.htm']",
                    "a[href$='transfer.htm']",
                ])

            id_match = (
                re.fullmatch(r"#([A-Za-z_][\w-]*)", selector)
                if selector
                else None
            )
            name_match = (
                re.fullmatch(
                    r"(?:[a-z][a-z0-9-]*)?\[name=['\"]([A-Za-z_][\w-]*)['\"]\]",
                    selector,
                )
                if selector
                else None
            )
            if id_match:
                selectors.append(
                    f"input[name='{id_match.group(1)}']"
                )
            elif name_match:
                selectors.append(f"#{name_match.group(1)}")

            def find_visible_element(driver):
                for candidate_selector in selectors:
                    for element in driver.find_elements(
                            By.CSS_SELECTOR,
                            candidate_selector,
                    ):
                        if element.is_displayed():
                            if action == "click":
                                href = str(
                                    element.get_attribute("href") or ""
                                ).lower()
                                if "/admin" in href or "administrator" in href:
                                    continue
                            return element
                return False

            try:
                return WebDriverWait(
                    self.driver,
                    target.get("timeout_seconds", 10),
                ).until(find_visible_element)
            except (InvalidSelectorException, TimeoutException):
                semantic_element = find_element_by_purpose(
                    self.driver,
                    target.get("purpose", ""),
                    action,
                )
                if semantic_element is not None:
                    href = str(
                        semantic_element.get_attribute("href") or ""
                    ).lower()
                    if "/admin" in href or "administrator" in href:
                        return None
                    return semantic_element

            return None

        return find_element_by_purpose(
            self.driver,
            target["purpose"],
            action
        )

    def click(self, target:dict) -> None:
        element = self.locate(target, "click")
        if element is None:
            raise ElementNotFoundError(target)

        href = str(element.get_attribute("href") or "").lower()
        if "/admin" in href or "administrator" in href:
            raise PermissionError(
                f"Administrator navigation is not allowed: {href}"
            )
        element.click()

    def verify(
            self,
            strategy,
            value,
            action) -> bool:
        return self.function_handler(
            strategy, 
            value, 
            action)

    def wait_for_purpose(self, purpose: str, action: str, timeout: int = 10):
        return WebDriverWait(self.driver, timeout).until(
            lambda driver: find_element_by_purpose(
                driver,
                purpose,
                action,
            )
        )

    def wait_for_page_ready(self, timeout: int = 10) -> bool:
        return WebDriverWait(self.driver, timeout).until(
            lambda driver: driver.execute_script(
                "return document.readyState"
            ) in {"interactive", "complete"}
        )

    def wait_for_text(self, expected: str, timeout: int = 15) -> bool:
        try:
            return WebDriverWait(self.driver, timeout).until(
                lambda driver: expected in driver.find_element(
                    By.TAG_NAME,
                    "body",
                ).text
            )
        except TimeoutException:
            return False

    def input(self, target: dict, entry_variable: str) -> None:
        element = self.locate(target, "input")
        if element is None:
            raise ElementNotFoundError({
                **target,
                "current_url": self.driver.current_url,
            })
        element.send_keys(entry_variable)

    def select(self, target:dict, entry_variable:str) -> None:
        if entry_variable is None:
            raise ValueError(
                f"Missing selection value for target: {target}"
            )
        element = self.locate(target, "select")
        if element is None:
            raise ElementNotFoundError(target)
        select = Select(element)
        requested_value = str(entry_variable).strip()
        matching_values = [
            option.get_attribute("value")
            for option in select.options
        ]
        if requested_value in matching_values:
            select.select_by_value(requested_value)
        else:
            matching_option = next(
                (
                    option
                    for option in select.options
                    if requested_value == option.text.strip()
                    or requested_value in option.text.strip()
                ),
                None,
            )
            if matching_option is None:
                raise ValueError(
                    f"No dropdown option matched requested value for target: {target}"
                )

            option_value = matching_option.get_attribute("value")
            if option_value:
                select.select_by_value(option_value)
            else:
                matching_option.click()

        selected_option = select.first_selected_option
        selected_text = selected_option.text.strip()
        selected_value = str(
            selected_option.get_attribute("value") or ""
        ).strip()
        if (
                requested_value != selected_text
                and requested_value != selected_value
                and requested_value not in selected_text
                and requested_value not in selected_value
        ):
            raise ValueError(
                f"Dropdown selection mismatch for {target}: "
                f"expected {requested_value!r}, got {selected_text or selected_value!r}"
            )

    def read_text(self, target: dict) -> str:
        element = self.locate(target, "inspect")
        if element is None:
            raise ElementNotFoundError(target)
        return element.text


    def function_handler(self, strategy: str, value: str, action: str) -> bool:
        pot_function = self.verify_if_function(strategy)

        if not pot_function:
            return False

        boolean_variable = pot_function(value)

        if boolean_variable:
            return True

        return False

    def verify_if_function(self, strategy: str) -> Optional[Callable]:
        # Check the global scope of the project
        converted_func = globals().get(strategy)

        if callable(converted_func):
            return converted_func

        # Check the class scope of the project
        converted_func = getattr(self, strategy, None)

        if callable(converted_func):
            return converted_func

        # Function was not found
        return None

    def navigate_to(self, website_url) -> bool:
        # Verify that the website provided exists
        try: 
            self.driver.get(website_url)
            return True
        except Exception:
            return False

    # Track whether the user is logged in to maximize reuse.
    def verify_login(
            self, 
            value: str) -> bool:
        """
        Verify if the user is logged in by checking for the presence of a login button.
        If the user has not logged into the account, 
        
        Args:
            driver (WebDriver): The Selenium WebDriver instance.
            username (str): The username for the account.
            password (str): The password for the account.
        """

        # Use login-specific controls. A generic text search can match
        # unrelated links such as the administrator panel.
        login_fields = self.driver.find_elements(
            By.CSS_SELECTOR,
            "input[name='username'], input[name='password'], #username, #password",
        )
        if any(field.is_displayed() for field in login_fields):
            return False

        logout_links = self.driver.find_elements(
            By.CSS_SELECTOR,
            "a[href*='logout'], input[value='Log Out'], button[value='Log Out']",
        )
        if any(link.is_displayed() for link in logout_links):
            return True

        login_url = self.driver.current_url.lower()
        if "/login.htm" in login_url:
            return False

        # An unknown public page is not proof of authentication.
        return False
