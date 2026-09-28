from src.GoalParser import GoalParser
from src.DiscoveryAgent import DiscoveryAgent
from src.ReplayEngine import ReplayEngine
from utils.json_retrieval import load_json_file


class BrowserAgent:
    def __init__(self, surface, policy, recorder, parameters, chatbot=None):
        self.surface = surface
        self.policy = policy
        self.recorder = recorder
        self.chatbot = chatbot
        self.parameters = parameters

    def discover(self, goal: str):

        discovery = DiscoveryAgent(
            surface=self.surface,
            policy=self.policy,
            recorder=self.recorder,
            chatbot=self.chatbot,
        )

        return discovery.run(
            goal = goal,
            parameters=self.parameters)

    def replay(self, artifact_path: str):
        artifact = load_json_file(artifact_path)

        replay=ReplayEngine(
            surface=self.surface,
            policy=self.policy,
            recorder=self.recorder,
            chatbot = self.chatbot
        )

        return replay.run(artifact, self.parameters)
