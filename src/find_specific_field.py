from typing import Optional
import re
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.by import By
from selenium.common.exceptions import StaleElementReferenceException
from utils import json_retrieval


def find_element_by_purpose(
        driver: WebDriver,
        purpose: str,
        action: str,
        standardize_str: bool = True
) -> Optional[WebElement]:
    """
    Dynamically locate a web element based on:
        1. The semantic purpose of the element
        2. The action that will be performed
        3. The element's attributes
        4. Positive keywords from the configuration
        5. Excluded/negative keywords from the configuration

    Args:
        driver: Selenium WebDriver instance.
        purpose: Semantic description of the element, e.g.
                 "login", "amount", "from account".
        action: Intended action, e.g.
                "click", "input", "select".
        standardize_str: Whether strings should be standardized.

    Returns:
        The best matching WebElement, or None if no suitable
        element can be found.
    """

    # ---------------------------------------------------------
    # 1. Standardize the purpose
    # ---------------------------------------------------------

    search_purpose = standardize_string(purpose)
    purpose_terms = [
        term
        for term in re.findall(r"[a-z0-9]+", str(purpose).lower())
        if term not in {
            "a", "an", "the", "to", "for", "of", "on", "with",
            "input", "enter", "fill", "type", "click", "select",
        }
    ]

    # ---------------------------------------------------------
    # 2. Load search configuration
    # ---------------------------------------------------------

    json_config = json_retrieval.load_json_file(
        "config\\config.json"
    )

    search_criteria = json_config.get(
        "element_search_criteria",
        {}
    )

    # ---------------------------------------------------------
    # 3. Find configuration for this purpose
    # ---------------------------------------------------------

    purpose_config = search_criteria.get(
        search_purpose,
        {}
    )

    excluded_words = purpose_config.get(
        "excluded_words",
        []
    )

    likely_categories = purpose_config.get(
        "likely_categories",
        {}
    )

    # Standardize excluded words
    excluded_words = [
        standardize_string(word)
        for word in excluded_words
    ]

    # ---------------------------------------------------------
    # 4. Determine what element types make sense for the action
    # ---------------------------------------------------------

    action_tags = {
        "click": [
            "a",
            "button",
            "input"
        ],

        "input": [
            "input",
            "textarea"
        ],

        "select": [
            "select"
        ]
    }

    possible_tags = action_tags.get(
        action.lower(),
        [
            "a",
            "button",
            "input",
            "select",
            "textarea"
        ]
    )

    # ---------------------------------------------------------
    # 5. Use configuration to narrow the element types
    # ---------------------------------------------------------

    if likely_categories:

        configured_tags = [
            tag.lower()
            for tag in likely_categories.keys()
        ]

        # Keep only tags appropriate for the action
        possible_tags = [
            tag
            for tag in configured_tags
            if tag in possible_tags
        ]

        # If configuration doesn't contain a compatible
        # element type, fall back to the action's defaults.
        if not possible_tags:
            possible_tags = action_tags.get(
                action.lower(),
                [
                    "a",
                    "button",
                    "input",
                    "select",
                    "textarea"
                ]
            )

    css_selector = ", ".join(possible_tags)

    # ---------------------------------------------------------
    # 6. Find candidate elements on the current page
    # ---------------------------------------------------------

    elements = driver.find_elements(
        By.CSS_SELECTOR,
        css_selector
    )

    # ---------------------------------------------------------
    # 7. Score each candidate
    # ---------------------------------------------------------

    candidates = []

    for element in elements:

        try:
            if not element.is_displayed():
                continue

            tag_name = element.tag_name.lower()

            # -------------------------------------------------
            # Collect useful attributes
            # -------------------------------------------------

            attributes = {
                "text": element.text,
                "value": element.get_attribute("value"),
                "aria-label": element.get_attribute("aria-label"),
                "placeholder": element.get_attribute("placeholder"),
                "title": element.get_attribute("title"),
                "name": element.get_attribute("name"),
                "id": element.get_attribute("id"),
                "class": element.get_attribute("class"),
                "type": element.get_attribute("type")
            }

            score = 0
            matched_attributes = []

            # -------------------------------------------------
            # Check every attribute
            # -------------------------------------------------

            for attribute_name, attribute_value in attributes.items():

                if not attribute_value:
                    continue

                standardized_value = standardize_string(
                    str(attribute_value)
                )

                # ---------------------------------------------
                # Positive match
                # ---------------------------------------------

                exact_match = search_purpose in standardized_value
                term_match = any(
                    term in standardized_value
                    for term in purpose_terms
                )

                if exact_match or term_match:

                    matched_attributes.append(
                        attribute_name
                    )

                    # Some attributes are more meaningful
                    # than others.
                    if attribute_name == "id":
                        score += 10

                    elif attribute_name == "name":
                        score += 9

                    elif attribute_name == "aria-label":
                        score += 8

                    elif attribute_name == "placeholder":
                        score += 8

                    elif attribute_name == "title":
                        score += 7

                    elif attribute_name == "text":
                        score += 6

                    elif attribute_name == "value":
                        score += 5

                    elif attribute_name == "class":
                        score += 2

                    elif attribute_name == "type":
                        score += 2

                    elif not exact_match:
                        score += 1

            # -------------------------------------------------
            # No positive match = probably not our element
            # -------------------------------------------------

            if score == 0:
                continue

            # -------------------------------------------------
            # Check excluded words
            # -------------------------------------------------

            excluded_match = False

            for excluded_word in excluded_words:

                for attribute_value in attributes.values():

                    if not attribute_value:
                        continue

                    standardized_value = standardize_string(
                        str(attribute_value)
                    )

                    if excluded_word in standardized_value:

                        excluded_match = True
                        break

                if excluded_match:
                    break

            # -------------------------------------------------
            # Reject candidates containing excluded words
            # -------------------------------------------------

            if excluded_match:
                continue

            # -------------------------------------------------
            # Give additional weight to correct element type
            # -------------------------------------------------

            if tag_name in possible_tags:
                score += 3

            # -------------------------------------------------
            # Save candidate
            # -------------------------------------------------

            candidates.append(
                (
                    score,
                    element,
                    matched_attributes
                )
            )

        except StaleElementReferenceException:
            continue

    # ---------------------------------------------------------
    # 8. Return the highest-scoring candidate
    # ---------------------------------------------------------

    if not candidates:
        print(
            f"[ELEMENT FINDER] Could not find element "
            f"for purpose '{purpose}' using action '{action}'."
        )

        return None

    candidates.sort(
        key=lambda candidate: candidate[0],
        reverse=True
    )

    best_score, best_element, matched_attributes = candidates[0]

    print(
        f"[ELEMENT FINDER] Purpose: '{purpose}'"
    )

    print(
        f"[ELEMENT FINDER] Action: '{action}'"
    )

    print(
        f"[ELEMENT FINDER] Found: "
        f"<{best_element.tag_name}>"
    )

    print(
        f"[ELEMENT FINDER] Score: {best_score}"
    )

    print(
        f"[ELEMENT FINDER] Matched attributes: "
        f"{matched_attributes}"
    )

    return best_element


def standardize_string(value: str) -> str:
    """
    Standardize a string for comparison.
    """

    if value is None:
        return ""

    value = str(value).lower().strip()

    # Remove spaces
    value = value.replace(" ", "")

    return value