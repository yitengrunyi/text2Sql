from enum import Enum



class DBType(Enum):
    MYSQL1 = ("MYSQL1", "MYSQL DB1")
    MYSQL2 = ("MYSQL2", "MYSQL DB2")
    ORACLE = ("ORACLE", "ORACLE DB")
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
        for db in DBType:
            if db.code == code:
                return db
        raise ValueError(f"未找到对应的数据库: {code}")
