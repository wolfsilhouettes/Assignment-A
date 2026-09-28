class ElementNotFoundError(RuntimeError):
    def __init__(self, target: dict):
        self.target = target
        super().__init__(
            f"Could not locate target: {target}"
        )