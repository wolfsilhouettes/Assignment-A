import copy
import re

from utils.json_retrieval import load_json_file

class GoalParser():
    def __init__(self, goal):
        self.goal = goal
        self.steps = load_json_file("config\\inputs.json")

    def extract_goal(self) -> dict:
        workflow = {}

        #print(f"the goal is {self.goal}")
            
        # Determine whether the goal is in the json file
        for qualities in self.steps.values():
            workflow_id = qualities["workflow_id"]

            if re.search(rf"\b{re.escape(workflow_id)}\b", self.goal, re.IGNORECASE):
                workflow = copy.deepcopy(qualities)
                break

        # If no workflow found, return an empty dictionary
        if not workflow:
            raise GoalValidationError("unsupported_goal", 
                                      "I could not identify a supported workflow")

        # If illegal words are found in the phrase, return an empty dictionary
        if self.validate_legal_command(self.goal, workflow) != "":
            raise GoalValidationError("unsafe_goal",
                                      f"This goal contains disallowed words like {self.validate_legal_command(self.goal, workflow)}.")

        # Verify that the requirements of the workflow are present
        input_definitions = copy.deepcopy(workflow["required_fields"])
        variablesDict = self.retrieve_required_variables(input_definitions)

        if not variablesDict:
            prompt = self.return_required_fields_string(workflow["required_fields"])
            raise GoalValidationError("missing_fields",
                                      prompt)

        workflow["input_definitions"] = input_definitions
        workflow["required_fields"] = variablesDict

        return workflow

    def return_required_fields_string(self, required_fields: dict) -> str:
            required_fields_text = ", ".join(
                f"{field} & {details.get('variable', 'value')}"
                for field, details in required_fields.items()
            )
            required_fields_text = required_fields_text.replace("_", " ")
            required_fields_text = required_fields_text.replace("{", "")
            required_fields_text = required_fields_text.replace("}", "")

            return f"Please provide the following information: {required_fields_text}."

    def validate_legal_command(
            self,
            user_entry: str,
            workflow: dict
    ) -> str:

        illegal_words_found = ""
        
        if not "illegal_words" in workflow:
            return illegal_words_found

        for illegal_word in workflow["illegal_words"]:
            if user_entry.find(illegal_word) > -1:
                illegal_words_found = f"\n {illegal_word}"

        return illegal_words_found

    def retrieve_required_variables(
            self, 
            required_fields) -> dict:
        tokens = re.findall(r"[\w$.,!?#-]+", self.goal, flags=re.UNICODE)
        normalized_tokens = [token.casefold() for token in tokens]
        keywords = list(required_fields)
        keyword_positions = {}

        for keyword in keywords:
            matches = [
                index
                for index, token in enumerate(normalized_tokens)
                if token == keyword.casefold()
            ]
            if len(matches) != 1:
                return {}
            keyword_positions[keyword] = matches[0]

        ordered_keywords = sorted(keywords, key=keyword_positions.__getitem__)
        parsed_values = {}
        for position, keyword in enumerate(ordered_keywords):
            start = keyword_positions[keyword] + 1
            end = (
                keyword_positions[ordered_keywords[position + 1]]
                if position + 1 < len(ordered_keywords)
                else len(tokens)
            )
            declaration = required_fields[keyword]
            value_tokens = self._clean_value_tokens(
                tokens[start:end],
                declaration.get("acceptable_characters", []),
            )
            value = self._parse_region_value(value_tokens, declaration)
            if value is None:
                return {}
            parsed_values[keyword] = value

        return {
            declaration["variable"]: parsed_values[keyword]
            for keyword, declaration in required_fields.items()
        }

    @staticmethod
    def _clean_value_tokens(tokens: list[str], acceptable_characters: list) -> list[str]:
        ignored_words = {
            str(item).casefold()
            for item in acceptable_characters
            if len(str(item)) > 1
        }
        punctuation = {
            str(item)
            for item in acceptable_characters
            if len(str(item)) == 1 and not str(item).isalnum()
        }
        cleaned_tokens = []
        for token in tokens:
            if token.casefold() in ignored_words:
                continue
            cleaned = token
            for character in punctuation:
                cleaned = cleaned.replace(character, "")
            if cleaned:
                cleaned_tokens.append(cleaned)
        return cleaned_tokens

    @staticmethod
    def _parse_region_value(tokens: list[str], declaration: dict):
        if not tokens:
            return None

        expected_type = declaration.get("expected_input_type", "variant").casefold()
        if expected_type in {"int", "integer"}:
            candidates = [
                token for token in tokens
                if token.lstrip("-").isdigit()
            ]
            return candidates[0] if len(candidates) == 1 else None

        if expected_type == "variant":
            minimum = declaration.get("# lower limit", 0)
            maximum = declaration.get("# upper limit", 0)
            candidates = []
            for token in tokens:
                digit_count = sum(character.isdigit() for character in token)
                if minimum and digit_count < minimum:
                    continue
                if maximum and digit_count > maximum:
                    continue
                if minimum or maximum:
                    candidates.append(token)
            return candidates[0] if len(candidates) == 1 else None

        if expected_type in {"str", "string"}:
            return " ".join(tokens)

        return None

    def buildConfidenceIntervalDict(
            self,
            required_fields: dict,
            missing_keyword: str,
            possibleWords: dict
    ) -> dict:

        confidenceIntervalDict = {}

        # Widdle down the possible number of words, skipping the missing keyword
        for present_keywords in required_fields:
            if present_keywords == missing_keyword:
                continue

            # Locate all keyword locations
            keyword_substring = self.return_substrings_with_keywords(present_keywords, required_fields)

            # Use the keyword locations to narrow down what the closest word is
            confidenceIntervalDict = self.return_confidence_intervals(
                possibleWords[present_keywords], 
                keyword_substring,
                present_keywords,
                confidenceIntervalDict)

        # Use process of elimination to find the potentially missing keyword (if any)
        if missing_keyword:
            confidenceIntervalDict = self.return_confidence_intervals(
                possibleWords[missing_keyword],
                keyword_substring,
                missing_keyword,
                confidenceIntervalDict
            )

        return confidenceIntervalDict

    def transform_text_to_variable(
            self,
            keywordDict: dict,
            required_fields: dict
    ) -> dict:

        variableDict = {}
        
        for requirement in required_fields:
            variable_name = required_fields[requirement]["variable"]
            # Ensure requirement found
            if requirement not in keywordDict:
                raise KeyError
            variableDict[variable_name] = keywordDict[requirement]

        return variableDict

    def determine_most_likely_word(
            self,
            confidenceIntervalDict: dict
    ) -> dict:
        
        keywordDict = {}

        # Perform an initial comparison for each keyword internally
        keywordDict = self.inner_confidence_interval_comparison(
            confidenceIntervalDict,
            keywordDict
        )

        #print(keywordDict)

        # Ensure that there are at least as many keywords as their are potential words
        duplicationSet = set()
        for keyword, possible_word in keywordDict.items():
            duplicationSet.add(possible_word)

        if len(duplicationSet) < len(keywordDict):
            return {}

        # Verify if there are any duplicates within the keywordDict
        duplicateTracker = {}
        verify_duplication = False
        for keyword, possible_word in keywordDict.items():
            if possible_word not in duplicateTracker:
                duplicateTracker[possible_word] = keyword
            if possible_word in duplicateTracker:
               shared_word = possible_word
               verify_duplication = True

        if not verify_duplication:
            return keywordDict

        # If there's potentially shared workflow, run AMONGST keywords to determine where the shared word belongs
        duplicateDict = {}
        for keyword, possible_word in keywordDict.items():
            if possible_word == shared_word:
                duplicateDict[keyword] = possible_word

        keywordDict = self.confidence_interval_comparison_shared(
            duplicateDict,
            confidenceIntervalDict,
            keywordDict,
            shared_word
        )

        return keywordDict

    def inner_confidence_interval_comparison(
            self,
            confidenceIntervalDict: dict,
            bestWord: dict
    ) -> dict:

        # SHARED WORDS, FIND THE SHARED WORD THAT FITS CLOSEST TO THE KEYWORD
        for keyword, words in confidenceIntervalDict.items():
            previous_smallest = 0
            for word in words:
                # Perform a run of what the most likely word is WITHIN the confidence interval
                smallest_within = self.return_smallest_confidence_interval(words[word])

                if previous_smallest == 0:
                    previous_smallest = smallest_within

                if smallest_within <= previous_smallest:
                    bestWord[keyword] = word
        return bestWord

    def confidence_interval_comparison_shared(
            self,
            wordTypeDict: dict,
            confidenceIntervalDict: dict,
            bestWord: dict,
            duplicated_word: str
    ) -> dict:

        previous_interval = 0 
        best_keyword = ""

        # SHARED WORDS, FIND THE SHARED WORD THAT FITS CLOSEST TO THE KEYWORD
        for keyword, shared_word in wordTypeDict.items():
            if shared_word != duplicated_word:
                continue

            # Find the best word between KEYWORDS
            interval_one = confidenceIntervalDict[keyword][shared_word]
            smallest_interval_one = self.return_smallest_confidence_interval(interval_one)
            #print(f"the closest instance of {shared_word} is {interval_one} for {keyword}")

            if previous_interval == 0:
                previous_interval = smallest_interval_one

            if smallest_interval_one <= previous_interval:
                previous_interval = smallest_interval_one
                best_keyword = keyword

            #print(f"the word {shared_word} best fits {best_keyword}")

        missing_keyword = ""

        # Figure out which key was the duplicate (there should only be one)
        for keyword, shared_word in wordTypeDict.items():
            if keyword != best_keyword:
                missing_keyword = keyword

        #print(f"the missing keyword is {missing_keyword}")

        # Remove the shared word from the keyword's location set
        if missing_keyword:
            del confidenceIntervalDict[missing_keyword][duplicated_word]
        #print(f"the new confidence interval is {confidenceIntervalDict}")

        # Recall the inner_confidence_interval
        bestWord = self.inner_confidence_interval_comparison(confidenceIntervalDict, bestWord)

        return bestWord

    def return_smallest_confidence_interval(
            self,
            confidence_intervals: set
    ) -> int:

        # Start off with the first item of the set
        smallest_interval = next(iter(confidence_intervals))
        
        for confidence_interval in confidence_intervals:
            if confidence_interval < smallest_interval:
                smallest_interval = confidence_interval

        return smallest_interval
 
    def retrieve_missing_keywords(
            self,
            requiredFields: dict
    ) -> list:

    # Return the missing keywords
        keywords_missing = []

        for keyword in requiredFields:
            if self.goal.find(keyword) == -1:
                keywords_missing.append(keyword)

        return keywords_missing

    def return_confidence_intervals(
            self,
            possibleWords: dict,
            parsed_substring: str,
            keyword: str,
            confidenceIntervalDict: dict
    ) -> dict:

        # Split the newly parsed string into words
        goal_words = parsed_substring.split()

        # Initialize variables
        goal_word_locations = []
        previous_location = len(goal_words) + 1

        # Retrieve the keyword locations from the parsed string
        goal_word_locations = self.find_possible_word_locations(
            goal_words,
            keyword
        )

        # Initialize the variable
        wordLocations = {}

        # locate the indices of the possible word in the new substring
        for word in possibleWords:
            locations = self.find_possible_word_locations(
                goal_words,
                word
            )
            #print(f"The locations for {word} are: {locations}")

            # If no locations are returned, the variable is likely not next to its keyword
            if not locations:
                wordLocations[word] = {previous_location}
                continue

            wordLocations = self.calculate_distance_from_keyword(
                wordLocations,
                goal_word_locations,
                locations,
                word
            )

        confidenceIntervalDict[keyword] = wordLocations
        return confidenceIntervalDict

    def calculate_distance_from_keyword(
            self,
            wordLocations: dict,
            goal_word_locations: list,
            possible_word_locations: list,
            possible_word: str
    ) -> dict:

        confidenceSet = set()

        for location in possible_word_locations:
            for keyword_location in goal_word_locations:
                # We only want to do locations that are greater than the keyword location
                if location > keyword_location:
                    #print(f"{possible_word} is a potential word with a location of {location}")
                    confidence_interval = location - keyword_location
                    confidenceSet.add(confidence_interval)

        wordLocations[possible_word] = confidenceSet
        return wordLocations

    def find_possible_word_locations(
            self,
            words: list,
            search_text: str
    ) -> list:
        indices = []

        for index, word in enumerate(words):
            if word.lower() == search_text.lower():
                indices.append(index)

        return indices

    def return_substrings_with_keywords(
            self,
            keyword: str,
            keywords: dict
    ) -> str:

        #Sanitize the goal based on the keyword's acceptable characters
        acceptable_characters = keywords[keyword]["acceptable_characters"]
        goal = self.goal

        for character in acceptable_characters:
            goal = goal.replace(character, "")

        words = goal.split()
        start_appending = False
        substring = ""

        for word in words:
            # If the keyword is present, start appending
            if word == keyword:
                start_appending = True

            if word in keywords and word != keyword:
                start_appending = False

            if start_appending == True:
                substring = f"{substring} {word}"

        # If there's another keyword, stop appending
        #print(substring)
        return substring

    def variant_type_helper_function(
            self,
            word: str,
            fieldDict: dict
    ) -> bool:
        
        # Defining VARIANT as a string that has numbers and characters
        # Verify if number limits exist for the variant variable type

        lower_limit = 0
        if "# lower limit" in fieldDict:
            lower_limit = fieldDict["# lower limit"]

        upper_limit = 0
        if "# upper limit" in fieldDict:
            upper_limit = fieldDict["# upper limit"]

        # If neither exist, the variable does not fit my definition of a VARIANT and cannot be identified through this channel. 
        # Notify the human controller since this would be a CODE error rather than a USER error
        if lower_limit == 0 and upper_limit == 0:
            raise ValueError("[VARIANT VARIABLE TYPE ERROR]. No lower limit or upper limit specified in the config file. Please provide \
            at least one criteria to identify the variable")

        # Verify that the upper limit is greater than the lower limit. Otherwise, notify the human of the code error
        if lower_limit >= upper_limit:
            raise ValueError("[VARIANT VARIABLE TYPE ERROR]. The lower limit in the config file is greater than or equal to \
            the upper limit. Please swap these numbers or delete the appropriate limit")

        #Loop through the characters in the word to verify whether the variant type fits the criteria
        num_count = 0

        for char in word:
            if char.isnumeric():
                num_count += 1

        # Use the count to verify whether this is my word
        if num_count < lower_limit and lower_limit > 0:
            return False

        # Ensure the upper_limit exists and that the number count is lower
        if num_count > upper_limit and upper_limit > 0:
            return False

        return True

    def retrieve_all_possible_words_for_keyword(
        self,
        fieldDict: dict
    ) -> dict:

        # Use the variable type to determine the most probable word
        # Retrieve all the possible words for that keyword -> most flexible to do a process of elimination to support varying sentence structures
        wordDict = {}

        for keyword in fieldDict:
            #Sanitize the goal based on the keyword's acceptable characters
            acceptable_characters = fieldDict[keyword]["acceptable_characters"]
            revised_goal = self.goal

            for character in acceptable_characters:
                revised_goal = revised_goal.replace(character, "")

            #print(f"the revised goal is: {revised_goal}")

            variable_type = fieldDict[keyword]["expected_input_type"]
            words = revised_goal.split()
    
            wordProx = set()
    
            # Find the word that fits its variable type
            for word in words:
                if variable_type == "int":
                    if word.isnumeric():
                        wordProx.add(word)
                elif variable_type == "str":
                    if word.find(fieldDict[keyword]) > -1:
                        wordProx.add(word)
                elif variable_type == "variant":
                    if self.variant_type_helper_function(word, fieldDict[keyword]):
                        #print("the word fits the variant type")
                        wordProx.add(word)
    
            # Add all the possible word choices to the dictionary
            wordDict[keyword] = wordProx

        return wordDict

class GoalValidationError(ValueError):
    def __init__(self, code, message, field=None):
        super().__init__(message)
        self.code = code
        self.field = field