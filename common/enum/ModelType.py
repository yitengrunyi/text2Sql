from enum import Enum




class ModelType(Enum):
    GPT_O1 = ("GPT_O1", "gpt-o1 model prediction")
    GPT_4o = ("GPT_4o", "gpt-4o model prediction")
    KIMI = ("KIMI", "kimi model prediction")
    def __init__(self, code, description, executor):
        self._code = code
        self._description = description
        self._executor = executor

    @property
    def code(self):
        return self._code

    @property
    def description(self):
        return self._description

    @property
    def executor(self):
        return self._executor

    @staticmethod
    def from_code(code: str):
        for model in ModelType:
            if model.code == code:
                return model
        raise ValueError(f"未找到对应的模型: {code}")
