from utils.json_retrieval import load_json_file
from src.browser_factory import create_driver
from src.BrowserAgent import BrowserAgent
from src.Chatbot import ChatBot
from src.RunRecorder import report_generator
from src.SafetyPolicy import SafetyPolicy
from src.SurfaceAdapter import SurfaceAdapter
from src.GoalParser import GoalParser, GoalValidationError
import argparse
from uuid import uuid4
from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchWindowException,
    WebDriverException,
)


def browser_session_closed(error: WebDriverException) -> bool:
    if isinstance(error, (InvalidSessionIdException, NoSuchWindowException)):
        return True

    message = str(error).lower()
    return any(
        phrase in message
        for phrase in (
            "invalid session id",
            "no such window",
            "target window already closed",
            "chrome not reachable",
            "disconnected: not connected to devtools",
        )
    )

def retrieve_parameters(report, goal, chatbot) -> dict:
    
    if goal == "":
        goal = chatbot.return_next_action(
                "Hello! I am an automated agent here to help you with your banking needs! What would you like me to do for you today?",
                human_review_mode=False,
                requires_input=True,
            )

    while goal != "":
        try:
            parameters = GoalParser(goal).extract_goal()
            break
        except GoalValidationError as error:
            report.record_event(
                "goal_rejected",
                code=error.code,
                message=error.args[0],
            )

            goal = chatbot.return_next_action(
                error.args[0],
                human_review_mode=False,
                requires_input=True,
            )

    return parameters


def main_entry(
        run_id: str, 
        mode: str, 
        artifact_path: str = "", 
        goal: str = "") -> None:
    # Start the recorder
    recorder = report_generator("evidence", run_id)

    close_driver_on_exit = True
    try:
        file_paths = load_json_file("config/paths.json")
    except:
        recorder.write_to_report("[CODE ERROR] Could not load config/paths.json")
        raise RuntimeError("config file not available: config/paths.json)")

    try:
        registry_path = file_paths.get("registry_path")
    except:
        recorder.write_to_report("[CODE ERROR] Could not load the registry path. Code is only compatible for Windows computers.")
        raise RuntimeError("Default registry path not available.")

    # Validate that the registry path is there
    if not registry_path:
        raise ValueError("Please enter the registry path for your default application in the paths.json file")

    # Create a driver for the user's default browser -> Only works with Windows
    try:
        driver = create_driver(registry_path)
        print("[INFO] Successfully created a WebDriver instance for the default browser.")
    except RuntimeError as e:
        raise RuntimeError("[CODE ERROR] Could not create a WebDriver instance for the default browser. Please ensure that the default browser is supported (Chrome, Edge, or Firefox).") from e

    startup_url = "https://parabank.parasoft.com/parabank/index.htm"

    try:
        driver.get(startup_url)
        print(f"[INFO] Opened ParaBank: {startup_url}")
    except Exception as e:
        recorder.record_event(
            "startup_navigation_failed",
            url=startup_url,
            error=str(e),
        )
        print(f"[WARN] Could not open ParaBank: {e}")

    try:
        chatbot = ChatBot(driver=driver, report=recorder)
        parameters = retrieve_parameters(recorder, goal, chatbot)

        surface = SurfaceAdapter(driver=driver)
        chatbot.show_runtime_controls()
        policy = SafetyPolicy()
        agent = BrowserAgent(
            surface=surface,
            policy=policy,
            recorder=recorder,
            chatbot=chatbot,
            parameters=parameters
        )

        if mode == "discover":
            agent.discover(goal)
        if mode == "replay":
            agent.replay(artifact_path)

    except WebDriverException as error:
        if browser_session_closed(error):
            recorder.record_event(
                "browser_closed",
                error_type=type(error).__name__,
                error=str(error),
            )
            print("[INFO] Browser closed. Exiting.")
        else:
            close_driver_on_exit = False
            recorder.record_event(
                "webdriver_error",
                error_type=type(error).__name__,
                error=str(error),
            )
            print(
                f"[ERROR] WebDriver error; browser left open for inspection: {error}"
            )
    finally:
        if close_driver_on_exit:
            try:
                driver.quit()
            except WebDriverException:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Run browser workflow discovery or replay.")
    parser.add_argument("mode", choices=("discover", "replay"))
    parser.add_argument("--goal", required=True)
    parser.add_argument("--artifact-path", default="")
    parser.add_argument("--run-id", default=None)
    arguments = parser.parse_args()

    if arguments.mode == "replay" and not arguments.artifact_path:
        parser.error("replay mode requires --artifact-path")

    main_entry(
        run_id=arguments.run_id or uuid4().hex,
        mode=arguments.mode,
        artifact_path=arguments.artifact_path,
        goal=arguments.goal,
    )


if __name__ == "__main__":
    main()