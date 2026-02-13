"""
Prompt Registry - 팩 등록/조회
"""
import logging
from typing import Optional, Dict
from pathlib import Path
import yaml
from app.prompts.schema import PromptPack

logger = logging.getLogger(__name__)


class PromptRegistry:
    """프롬프트 팩 레지스트리"""
    
    def __init__(self, packs_dir: Optional[Path] = None):
        self._packs: Dict[str, PromptPack] = {}
        self.packs_dir = packs_dir or Path(__file__).parent / "packs"
        self._load_packs()
    
    def _load_packs(self):
        """packs 디렉토리에서 YAML 파일 로드"""
        if not self.packs_dir.exists():
            logger.warning(f"Packs directory not found: {self.packs_dir}")
            return
        
        for yaml_file in self.packs_dir.glob("*.yaml"):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    pack = PromptPack(**data)
                    self.register(pack)
                    logger.info(f"Loaded prompt pack: {pack.id} from {yaml_file.name}")
            except Exception as e:
                logger.error(
                    f"Failed to load prompt pack from {yaml_file}",
                    extra={"file": str(yaml_file), "error": str(e)},
                    exc_info=True
                )
    
    def register(self, pack: PromptPack):
        """팩 등록"""
        if pack.id in self._packs:
            logger.warning(f"Prompt pack {pack.id} already registered, overwriting")
        self._packs[pack.id] = pack
    
    def get(self, pack_id: str) -> Optional[PromptPack]:
        """팩 조회"""
        return self._packs.get(pack_id)
    
    def list_all(self) -> list[PromptPack]:
        """모든 팩 목록 반환"""
        return list(self._packs.values())

