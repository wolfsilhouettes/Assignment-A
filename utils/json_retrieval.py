import json

def load_json_file(file_path: str) -> dict:
    """
    Load a JSON file and return its contents as a dictionary.

    Args:
        file_path (str): The path to the JSON file.

    Returns:
        dict: The contents of the JSON file as a dictionary.
    """

    with open(file_path, 'r') as file:
        data = json.load(file)
    return data