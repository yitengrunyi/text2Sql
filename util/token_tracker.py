"""
Token Usage 追踪器模块

用于在单个请求处理流程中累积所有 LLM 调用的 token 使用量，
并在最终响应时按模型聚合输出。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from collections import defaultdict
import threading


@dataclass
class CompletionTokenDetails:
    """Completion Token 详细信息"""
    reasoning_tokens: int = 0
    text_tokens: int = 0
    audio_tokens: int = 0
    accepted_prediction_tokens: int = 0
    rejected_prediction_tokens: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "reasoning_tokens": self.reasoning_tokens,
            "text_tokens": self.text_tokens,
            "audio_tokens": self.audio_tokens,
            "accepted_prediction_tokens": self.accepted_prediction_tokens,
            "rejected_prediction_tokens": self.rejected_prediction_tokens
        }


@dataclass
class PromptTokenDetails:
    """Prompt Token 详细信息"""
    text_tokens: int = 0
    image_tokens: int = 0
    audio_tokens: int = 0
    cached_tokens: int = 0
    cache_creation_tokens: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "text_tokens": self.text_tokens,
            "image_tokens": self.image_tokens,
            "audio_tokens": self.audio_tokens,
            "cached_tokens": self.cached_tokens,
            "cache_creation_tokens": self.cache_creation_tokens
        }


@dataclass
class SingleCallUsage:
    """单次 LLM 调用的 usage 信息"""
    llm_model: str  # 请求时使用的模型名 (如 "gpt-4.1")
    real_model: str  # API 返回的实际模型名
    completion_tokens: int = 0
    prompt_tokens: int = 0
    total_tokens: int = 0
    completion_tokens_details: CompletionTokenDetails = field(default_factory=CompletionTokenDetails)
    prompt_tokens_details: PromptTokenDetails = field(default_factory=PromptTokenDetails)


def _safe_int(value: Any) -> int:
    """安全地将值转换为 int，None 或无效值返回 0"""
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _extract_dict(obj: Any) -> Dict[str, Any]:
    """
    从对象中提取字典。
    处理 Pydantic model、dict 或其他对象。
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    # 处理 Pydantic model 或其他有 model_dump/dict 方法的对象
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()
    if hasattr(obj, 'dict'):
        return obj.dict()
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    return {}


class TokenTracker:
    """
    Token 使用量追踪器

    用于在单个请求处理流程中累积所有 LLM 调用的 token 使用量，
    并在最终响应时按模型聚合输出。
    """

    def __init__(self):
        self._usages: List[SingleCallUsage] = []
        self._lock = threading.Lock()

    def record(self, usage: SingleCallUsage) -> None:
        """记录单次 LLM 调用的 usage"""
        with self._lock:
            self._usages.append(usage)

    def record_from_response(
        self,
        llm_model: str,
        response_data: Dict[str, Any]
    ) -> None:
        """
        从 API 响应中提取并记录 usage 信息

        Args:
            llm_model: 请求时使用的模型名
            response_data: API 响应的完整 JSON 数据
        """
        usage_data = response_data.get("usage")
        if not usage_data:
            return

        usage_dict = _extract_dict(usage_data)

        # 提取实际模型名
        real_model = response_data.get("model", llm_model)

        # 提取 completion_tokens_details
        completion_details_raw = usage_dict.get("completion_tokens_details")
        completion_details_data = _extract_dict(completion_details_raw)
        completion_details = CompletionTokenDetails(
            reasoning_tokens=_safe_int(completion_details_data.get("reasoning_tokens")),
            text_tokens=_safe_int(completion_details_data.get("text_tokens")),
            audio_tokens=_safe_int(completion_details_data.get("audio_tokens")),
            accepted_prediction_tokens=_safe_int(completion_details_data.get("accepted_prediction_tokens")),
            rejected_prediction_tokens=_safe_int(completion_details_data.get("rejected_prediction_tokens"))
        )

        # 提取 prompt_tokens_details
        prompt_details_raw = usage_dict.get("prompt_tokens_details")
        prompt_details_data = _extract_dict(prompt_details_raw)
        prompt_details = PromptTokenDetails(
            text_tokens=_safe_int(prompt_details_data.get("text_tokens")),
            image_tokens=_safe_int(prompt_details_data.get("image_tokens")),
            audio_tokens=_safe_int(prompt_details_data.get("audio_tokens")),
            cached_tokens=_safe_int(prompt_details_data.get("cached_tokens")),
            cache_creation_tokens=_safe_int(prompt_details_data.get("cache_creation_tokens"))
        )

        single_usage = SingleCallUsage(
            llm_model=llm_model,
            real_model=real_model,
            completion_tokens=_safe_int(usage_dict.get("completion_tokens")),
            prompt_tokens=_safe_int(usage_dict.get("prompt_tokens")),
            total_tokens=_safe_int(usage_dict.get("total_tokens")),
            completion_tokens_details=completion_details,
            prompt_tokens_details=prompt_details
        )

        self.record(single_usage)

    def get_aggregated_usage(self) -> List[Dict[str, Any]]:
        """
        按模型聚合所有 usage 并返回最终格式

        Returns:
            按 llm_model 分组聚合的 usage 列表
        """
        with self._lock:
            if not self._usages:
                return []

            # 按 llm_model 分组聚合
            aggregated: Dict[str, Dict[str, Any]] = {}

            for usage in self._usages:
                key = usage.llm_model

                if key not in aggregated:
                    aggregated[key] = {
                        "llm_model": usage.llm_model,
                        "real_model": usage.real_model,
                        "completion_tokens": 0,
                        "prompt_tokens": 0,
                        "total_tokens": 0,
                        "completion_tokens_details": {
                            "reasoning_tokens": 0,
                            "text_tokens": 0,
                            "audio_tokens": 0,
                            "accepted_prediction_tokens": 0,
                            "rejected_prediction_tokens": 0
                        },
                        "prompt_tokens_details": {
                            "text_tokens": 0,
                            "image_tokens": 0,
                            "audio_tokens": 0,
                            "cached_tokens": 0,
                            "cache_creation_tokens": 0
                        }
                    }

                agg = aggregated[key]

                # 累加 tokens
                agg["completion_tokens"] += usage.completion_tokens
                agg["prompt_tokens"] += usage.prompt_tokens
                agg["total_tokens"] += usage.total_tokens

                # 累加 completion_tokens_details
                details = usage.completion_tokens_details.to_dict()
                for k, v in details.items():
                    agg["completion_tokens_details"][k] += v

                # 累加 prompt_tokens_details
                prompt_details = usage.prompt_tokens_details.to_dict()
                for k, v in prompt_details.items():
                    agg["prompt_tokens_details"][k] += v

            return list(aggregated.values())

    def clear(self) -> None:
        """清空所有记录"""
        with self._lock:
            self._usages.clear()

    def __len__(self) -> int:
        """返回记录的调用次数"""
        with self._lock:
            return len(self._usages)
