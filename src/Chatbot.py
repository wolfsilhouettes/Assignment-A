from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import WebDriverException
import json
from typing import Optional

from src.RunRecorder import report_generator


class ChatBot:

    def __init__(self, driver: WebDriver, report: report_generator):
        self.driver = driver
        self.report = report
        self.control_state = "AUTOMATING"

        # Track the page where the chatbot currently exists.
        self.chatbot_url = None

    def show_runtime_controls(self, message="Agent is running"):
        """Keep a non-blocking human-control panel available during a run."""
        self.driver.execute_script("""
            const message = arguments[0];
            let panel = document.getElementById("python-runtime-controls");
            if (!panel) {
                panel = document.createElement("div");
                panel.id = "python-runtime-controls";
                panel.style.cssText = [
                    "position:fixed", "left:20px", "bottom:20px", "z-index:2147483647",
                    "background:white", "border:2px solid #333", "padding:12px",
                    "box-shadow:0 5px 20px rgba(0,0,0,.35)", "font-family:Arial,sans-serif"
                ].join(";");
                panel.innerHTML = `
                    <div id="python-runtime-message" style="margin-bottom:8px"></div>
                    <div id="python-runtime-state" style="margin-bottom:8px;font-weight:bold"></div>
                    <button id="python-human-control" type="button">HUMAN_CONTROL</button>
                    <button id="python-return-control" type="button" disabled>RETURN_CONTROL_TO_AGENT</button>
                `;
                document.body.appendChild(panel);
                panel.dataset.controlState = "AUTOMATING";
                panel.querySelector("#python-human-control").onclick = () => {
                    panel.dataset.controlState = "HUMAN_CONTROL";
                    panel.querySelector("#python-human-control").disabled = true;
                    panel.querySelector("#python-return-control").disabled = false;
                    panel.querySelector("#python-runtime-state").textContent = "Human control active";
                };
                panel.querySelector("#python-return-control").onclick = () => {
                    panel.dataset.controlState = "RETURN_CONTROL_TO_AGENT";
                    panel.querySelector("#python-human-control").disabled = false;
                    panel.querySelector("#python-return-control").disabled = true;
                    panel.querySelector("#python-runtime-state").textContent = "Returning control to agent";
                };
            }
            panel.querySelector("#python-runtime-message").textContent = message;
            panel.querySelector("#python-runtime-state").textContent =
                panel.dataset.controlState === "HUMAN_CONTROL" ? "Human control active" : "Agent control active";
        """, message)
        self.chatbot_url = self.driver.current_url

    def wait_for_agent_control(self):
        """Pause at an action boundary until the operator returns control."""
        self.show_runtime_controls()
        state = self.driver.execute_script("""
            const panel = document.getElementById("python-runtime-controls");
            return panel ? panel.dataset.controlState : "AUTOMATING";
        """)
        if state != "HUMAN_CONTROL":
            return

        self.control_state = "HUMAN_CONTROL"
        self.report.record_handoff(
            reason="Operator selected HUMAN_CONTROL.",
            control_state="HUMAN_CONTROL",
        )
        def control_returned(driver):
            panel_exists = driver.execute_script(
                "return document.getElementById('python-runtime-controls') !== null;"
            )
            if not panel_exists:
                self.show_runtime_controls("Human control remains active")
                return False

            return driver.execute_script("""
                const panel = document.getElementById("python-runtime-controls");
                return panel.dataset.controlState === "RETURN_CONTROL_TO_AGENT";
            """)

        WebDriverWait(
            self.driver,
            86400,
            poll_frequency=0.1,
        ).until(control_returned)
        self.control_state = "AUTOMATING"
        self.report.record_event(
            "control_returned",
            control_state="RETURN_CONTROL_TO_AGENT",
        )

    def request_intervention(self, reason: str, context: dict) -> str:
        """Show a blocked-state request with enough evidence for an operator."""
        safe_context = self.report.redact(context)
        try:
            screenshot_path = self.report.capture_screenshot(
                self.driver,
                name="intervention",
            )
            safe_context["screenshot_path"] = str(screenshot_path)
        except Exception as error:
            safe_context["screenshot_error"] = str(error)

        message = (
            f"Automation is blocked: {reason}\n\n"
            "Intervention context:\n"
            f"{json.dumps(safe_context, indent=2, ensure_ascii=True)}\n\n"
            "Resolve the issue in the browser, then select Complete."
        )
        return self.return_next_action(
            message,
            human_review_mode=True,
            requires_input=False,
            context=safe_context,
        )

    # ==========================================================
    # WAIT FOR USER RESPONSE
    # ==========================================================

    def return_next_action(
            self,
            relayed_message: str,
            human_review_mode: bool,
            requires_input: bool,
            context: Optional[dict] = None,
        ) -> str:

        print("[CHATBOT] Waiting for user interaction...")

        # Inject chatbot on the current page.
        self.show(
            relayed_message,
            human_review_mode,
            requires_input
        )

        # ------------------------------------------------------
        # Wait until the user responds.
        #
        # WebDriverWait is preferable to your while loop because
        # Selenium periodically checks the condition while the
        # browser remains available for normal user interaction.
        # ------------------------------------------------------

        response = WebDriverWait(
            self.driver,
            300,
            poll_frequency=0.1
        ).until(
            lambda driver: self._wait_for_chatbot_response(
                relayed_message,
                human_review_mode,
                requires_input
            )
        )

        response = str(response).strip().lower()

        print(f"[CHATBOT] User response: {response}")

        # ------------------------------------------------------
        # Write to report ONCE.
        #
        # Previously this was inside your while loop, which could
        # write the same information repeatedly.
        # ------------------------------------------------------

        if human_review_mode:
            self.report.record_handoff(
                reason=relayed_message,
                response=response,
                context=context,
            )
        else:
            self.report.record_event(
                "chatbot_prompt",
                message=relayed_message,
                requires_input=requires_input,
            )
            self.report.record_event(
                "user_response",
                response=response,
                requires_input=requires_input,
            )

        # ------------------------------------------------------
        # Convert chatbot response into next action.
        # ------------------------------------------------------

        if not requires_input:
            return response

        return response
    # ==========================================================
    # WAIT CONDITION
    # ==========================================================

    def _wait_for_chatbot_response(
            self,
            relayed_message: str,
            human_review_mode: bool,
            requires_input: bool
        ):

        try:
            current_url = self.driver.current_url
            chatbot_exists = self.driver.execute_script("""
                return document.getElementById(
                    "python-chatbot"
                ) !== null;
            """)

            # ----------------------------------------------
            # Page changed OR chatbot disappeared
            # ----------------------------------------------

            if (
                self.chatbot_url != current_url
                or not chatbot_exists
            ):

                print(
                    "[CHATBOT] Page changed or chatbot "
                    "disappeared."
                )

                self.show(
                    relayed_message,
                    human_review_mode,
                    requires_input
                )

            response = self.get_response()

            if response:
                return response

            return False

        except Exception as e:
            if isinstance(e, WebDriverException):
                raise
            print(
                f"[CHATBOT] Waiting for page: {e}"
            )
            return False


    # ==========================================================
    # SHOW CHATBOT
    # ==========================================================

    def show(
            self,
            relayed_message: str,
            requires_review: bool,
            requires_input: bool
        ) -> None:

        print("[CHATBOT] Injecting chatbot...")

        script = """
        const relayedMessage = arguments[0];
        const requiresReview = arguments[1];
        const requiresInput = arguments[2];

        // --------------------------------------------------
        // Remove existing chatbot
        // --------------------------------------------------

        const existing =
            document.getElementById("python-chatbot");

        if (existing) {
            existing.remove();
        }


        // --------------------------------------------------
        // Create chatbot
        // --------------------------------------------------

        const chatbot =
            document.createElement("div");

        chatbot.id = "python-chatbot";


        chatbot.innerHTML = `

            <!-- Chatbot Header -->

            <div style="
                background: #333;
                color: white;
                padding: 15px;
                font-weight: bold;
                flex-shrink: 0;
            ">
                Browser Assistant
            </div>


            <!-- Chat Messages -->

            <div id="python-chat-messages" style="
                padding: 15px;
                flex: 1;
                overflow-y: auto;
                box-sizing: border-box;
                min-height: 0;
            ">

                <div id="python-chat-message-text" style="
                    margin-bottom: 20px;
                ">
                </div>


                <div id="python-chat-options" style="
                    display: flex;
                    flex-direction: column;
                    gap: 10px;
                ">
                </div>

            </div>


            <!-- Text Input Area -->

            <div
                id="python-chat-input-area"
                style="
                    display: none;
                    gap: 5px;
                    padding: 10px;
                    border-top: 1px solid #ccc;
                    background: white;
                    box-sizing: border-box;
                    flex-shrink: 0;
                "
            >
            </div>


            <!-- Hidden Response Field -->

            <input
                id="python-chat-response"
                type="hidden"
                value=""
            >
        `;


        // --------------------------------------------------
        // Chatbot styling
        // --------------------------------------------------

        chatbot.style.position = "fixed";

        chatbot.style.right = "20px";

        chatbot.style.bottom = "20px";

        chatbot.style.width = "350px";

        chatbot.style.height = "450px";

        chatbot.style.backgroundColor = "white";

        chatbot.style.border = "2px solid black";

        chatbot.style.borderRadius = "10px";

        chatbot.style.boxShadow =
            "0 5px 20px rgba(0,0,0,0.5)";

        chatbot.style.zIndex = "2147483647";

        chatbot.style.display = "flex";

        chatbot.style.flexDirection = "column";

        chatbot.style.overflow = "hidden";

        chatbot.style.boxSizing = "border-box";


        // --------------------------------------------------
        // Add chatbot to page
        // --------------------------------------------------

        document.body.appendChild(chatbot);


        // --------------------------------------------------
        // Display Python's message
        // --------------------------------------------------

        document.getElementById(
            "python-chat-message-text"
        ).textContent = relayedMessage;
        document.getElementById(
            "python-chat-message-text"
        ).style.whiteSpace = "pre-wrap";


        // --------------------------------------------------
        // Get elements
        // --------------------------------------------------

        const options =
            document.getElementById(
                "python-chat-options"
            );

        const inputArea =
            document.getElementById(
                "python-chat-input-area"
            );


        // --------------------------------------------------
        // Submit response
        // --------------------------------------------------

        function submitResponse(response) {

            console.log(
                "[CHATBOT] Response:",
                response
            );


            // Store response in hidden input

            const responseElement =
                document.getElementById(
                    "python-chat-response"
                );

            if (responseElement) {

                responseElement.value =
                    response;
            }


            // Store response as attribute

            chatbot.setAttribute(
                "data-response",
                response
            );


            // Prevent multiple selections

            const buttons =
                options.querySelectorAll(
                    "button"
                );

            buttons.forEach(
                button => {
                    button.disabled = true;
                }
            );


            // Disable text input

            const textInput =
                document.getElementById(
                    "python-chat-input"
                );

            if (textInput) {

                textInput.disabled = true;
            }


            // Disable send button

            const sendButton =
                document.getElementById(
                    "python-chat-send"
                );

            if (sendButton) {

                sendButton.disabled = true;
            }


            console.log(
                "[CHATBOT] Response stored:",
                chatbot.getAttribute(
                    "data-response"
                )
            );
        }


        // ==================================================
        // MODE 1: USER INPUT
        // ==================================================

        if (requiresInput) {

            console.log(
                "[CHATBOT] Input mode enabled"
            );


            inputArea.style.display =
                "flex";


            inputArea.innerHTML = `

                <input
                    id="python-chat-input"
                    type="text"
                    placeholder="Type your response..."
                    style="
                        flex: 1;
                        padding: 10px;
                        border: 1px solid #aaa;
                        border-radius: 5px;
                        box-sizing: border-box;
                        min-width: 0;
                    "
                >

                <button
                    id="python-chat-send"
                    style="
                        padding: 10px 15px;
                        cursor: pointer;
                        flex-shrink: 0;
                    "
                >
                    Send
                </button>

            `;


            function submitTextResponse() {

                const input =
                    document.getElementById(
                        "python-chat-input"
                    );

                const response =
                    input.value.trim();


                if (response === "") {

                    console.log(
                        "[CHATBOT] Empty response ignored."
                    );

                    return;
                }


                submitResponse(
                    response
                );
            }


            document.getElementById(
                "python-chat-send"
            ).addEventListener(
                "click",
                function() {

                    submitTextResponse();

                }
            );


            document.getElementById(
                "python-chat-input"
            ).addEventListener(
                "keydown",
                function(event) {

                    if (event.key === "Enter") {

                        event.preventDefault();

                        submitTextResponse();

                    }

                }
            );


            document.getElementById(
                "python-chat-input"
            ).focus();


        // ==================================================
        // MODE 2: HUMAN REVIEW / COMPLETE
        // ==================================================

        } else if (requiresReview) {

            console.log(
                "[CHATBOT] Human review mode enabled"
            );


            const completeButton =
                document.createElement(
                    "button"
                );


            completeButton.textContent =
                "Complete";


            completeButton.style.padding =
                "10px";


            completeButton.style.cursor =
                "pointer";


            completeButton.addEventListener(
                "click",
                function() {

                    submitResponse(
                        "complete"
                    );

                }
            );


            options.appendChild(
                completeButton
            );


        // ==================================================
        // MODE 3: YES / NO / HUMAN REVIEW
        // ==================================================

        } else {

            console.log(
                "[CHATBOT] Yes/No/Human Review mode enabled"
            );


            // ------------------------------------------------
            // YES
            // ------------------------------------------------

            const yesButton =
                document.createElement(
                    "button"
                );

            yesButton.textContent =
                "Yes";

            yesButton.style.padding =
                "10px";

            yesButton.style.cursor =
                "pointer";


            yesButton.addEventListener(
                "click",
                function() {

                    submitResponse(
                        "yes"
                    );

                }
            );


            options.appendChild(
                yesButton
            );


            // ------------------------------------------------
            // NO
            // ------------------------------------------------

            const noButton =
                document.createElement(
                    "button"
                );

            noButton.textContent =
                "No";

            noButton.style.padding =
                "10px";

            noButton.style.cursor =
                "pointer";


            noButton.addEventListener(
                "click",
                function() {

                    submitResponse(
                        "no"
                    );

                }
            );


            options.appendChild(
                noButton
            );


            // ------------------------------------------------
            // HUMAN REVIEW
            // ------------------------------------------------

            const reviewButton =
                document.createElement(
                    "button"
                );

            reviewButton.textContent =
                "Human Review";

            reviewButton.style.padding =
                "10px";

            reviewButton.style.cursor =
                "pointer";


            reviewButton.addEventListener(
                "click",
                function() {

                    submitResponse(
                        "human_review"
                    );

                }
            );


            options.appendChild(
                reviewButton
            );
        }


        console.log(
            "[CHATBOT] CHATBOT INJECTED"
        );
        """


        self.driver.execute_script(
            script,
            relayed_message,
            requires_review,
            requires_input
        )


        # Remember which page contains this chatbot.
        self.chatbot_url = self.driver.current_url


        print(
            "[CHATBOT] Injection complete."
        )


    # ==========================================================
    # GET RESPONSE
    # ==========================================================

    def get_response(self):

        response = self.driver.execute_script("""

            const chatbot =
                document.getElementById(
                    "python-chatbot"
                );

            if (!chatbot) {
                return "";
            }


            const element =
                document.getElementById(
                    "python-chat-response"
                );


            if (!element) {
                return "";
            }


            return element.value || "";

        """)

        return response


    # ==========================================================
    # SEND MESSAGE
    # ==========================================================

    def send_message(self, message: str):

        self.driver.execute_script("""

            const messages =
                document.getElementById(
                    "python-chat-messages"
                );


            if (!messages) {
                return;
            }


            const botMessage =
                document.createElement(
                    "div"
                );


            botMessage.textContent =
                arguments[0];


            botMessage.style.cssText = `

                margin: 8px 0;
                padding: 8px;
                background: #333;
                color: white;
                border-radius: 5px;

            `;


            messages.appendChild(
                botMessage
            );


            messages.scrollTop =
                messages.scrollHeight;

        """, message)