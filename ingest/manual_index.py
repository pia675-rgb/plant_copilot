"""
manual_index.py
---------------
매뉴얼이 폴더 안에 폴더 안에 깊게 중첩되어 있어도 잘 찾도록 하는 인덱스 모듈.

사용법:
    from plant_copilot.ingest.manual_index import ManualIndex

    index = ManualIndex()          # 서버 시작 시 한 번 생성
    # 또는
    index = ManualIndex(force_rebuild=True)

    path = index.find_path("im_e_sievers-m9-manual_dlm_77020-02.pdf")
    manuals = index.find_by_maker("Sievers")
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================
# 설정 (필요시 config.py에서 덮어쓰기)
# ============================================================
# 폴더는 config 를 따른다. 상대경로로 못박아 두면 두 가지가 깨진다.
#   · 서버를 다른 디렉터리에서 띄우면 매뉴얼을 못 찾는다
#   · COPILOT_DATA_DIR 로 데모 자료를 지정해도 이 인덱스만 실물을 계속 본다
#     — 시연 당일 자료는 데모로 바꿨는데 매뉴얼만 실물을 가리키게 된다
# 캐시는 생성물이므로 derived/ 에 둔다. data/ 는 사람이 넣는 문서만 두는 자리다.
try:
    import config as _cfg
    DEFAULT_MANUALS_DIR = Path(_cfg.MANUAL_DIR)
    INDEX_CACHE_FILE = Path(_cfg.DERIVED_DIR) / "manual_index_cache.json"
except Exception:  # config 없이 단독 실행할 때
    DEFAULT_MANUALS_DIR = Path("data/manuals")
    INDEX_CACHE_FILE = Path("derived/manual_index_cache.json")


@dataclass
class ManualInfo:
    filename: str
    full_path: str
    relative_path: str
    maker: str
    category: str
    size_mb: float


class ManualIndex:
    def __init__(
        self,
        manuals_dir: str | Path = DEFAULT_MANUALS_DIR,
        force_rebuild: bool = False,
        use_cache: bool = True,
    ):
        self.manuals_dir = Path(manuals_dir)
        self._by_filename: Dict[str, ManualInfo] = {}
        self._by_maker: Dict[str, List[ManualInfo]] = {}
        self._all: List[ManualInfo] = []

        if use_cache and not force_rebuild and INDEX_CACHE_FILE.exists():
            try:
                self._load_cache()
                logger.info(f"[ManualIndex] 캐시 로드 완료: {len(self._all)}개 매뉴얼")
                return
            except Exception as e:
                logger.warning(f"[ManualIndex] 캐시 로드 실패, 재스캔합니다: {e}")

        self.rebuild()

    # ----------------------------------------------------------
    # 핵심: 전체 재스캔
    # ----------------------------------------------------------
    def rebuild(self) -> None:
        """data/manuals 전체를 재귀적으로 스캔해서 인덱스를 새로 만듭니다."""
        logger.info(f"[ManualIndex] 스캔 시작: {self.manuals_dir.resolve()}")

        self._by_filename.clear()
        self._by_maker.clear()
        self._all.clear()

        if not self.manuals_dir.exists():
            logger.error(f"[ManualIndex] 폴더가 존재하지 않습니다: {self.manuals_dir}")
            return

        count = 0
        for pdf_path in self.manuals_dir.rglob("*.pdf"):
            if not pdf_path.is_file():
                continue

            try:
                info = self._extract_info(pdf_path)
                self._register(info)
                count += 1
            except Exception as e:
                logger.warning(f"[ManualIndex] 스킵: {pdf_path} → {e}")

        # 대소문자 무시 검색을 위해 소문자 키도 추가
        for info in list(self._by_filename.values()):
            lower_name = info.filename.lower()
            if lower_name not in self._by_filename:
                self._by_filename[lower_name] = info

        self._save_cache()
        logger.info(f"[ManualIndex] 스캔 완료: 총 {count}개 매뉴얼 인덱싱됨")

    def _extract_info(self, pdf_path: Path) -> ManualInfo:
        """경로에서 메이커 / 카테고리 정보를 최대한 추출"""
        rel = pdf_path.relative_to(self.manuals_dir)
        parts = [p for p in rel.parts[:-1]]  # 파일명 제외한 폴더들

        maker = "Unknown"
        category = "General"

        # 폴더 이름에서 메이커 추정 (우선순위 높은 것부터)
        maker_candidates = []
        for part in reversed(parts):  # 깊은 폴더부터
            cleaned = part.strip()
            if cleaned.lower() in ("카탈로그", "catalog", "catalogue", "manuals", "data"):
                continue
            if "catalogue" in cleaned.lower() or "catalog" in cleaned.lower():
                continue
            maker_candidates.append(cleaned)

        if maker_candidates:
            maker = maker_candidates[0]

        # 더 정교한 메이커 추출 규칙 (필요시 추가)
        maker = self._normalize_maker(maker, pdf_path.name)

        # 카테고리 추정
        for part in parts:
            low = part.lower()
            if any(k in low for k in ("toc", "analyzer", "instrument", "flow", "pressure", "level")):
                category = part
                break

        size_mb = round(pdf_path.stat().st_size / (1024 * 1024), 2)

        return ManualInfo(
            filename=pdf_path.name,
            full_path=str(pdf_path.resolve()),
            relative_path=str(rel).replace("\\", "/"),
            maker=maker,
            category=category,
            size_mb=size_mb,
        )

    def _normalize_maker(self, raw_maker: str, filename: str) -> str:
        """파일명과 폴더명을 보고 메이커를 정규화"""
        filename_lower = filename.lower()
        raw_lower = raw_maker.lower()

        # 잘 알려진 메이커 매핑
        known = {
            "sievers": "Sievers",
            "veolia": "Sievers",
            "tokyo keiso": "Tokyo Keiso",
            "tokyo_keiso": "Tokyo Keiso",
            "fg_tokyo": "Tokyo Keiso",
            "mettler": "Mettler Toledo",
            "hach": "Hach",
            "endress": "Endress+Hauser",
            "e+h": "Endress+Hauser",
            "yokogawa": "Yokogawa",
            "abb": "ABB",
            "siemens": "Siemens",
            "fuji": "Fuji Electric",
            "smc": "SMC",
            "pms": "Particle Measuring Systems",
            "oribisphere": "Oribisphere",
            "hitrol": "Hitrol",
        }

        for key, normalized in known.items():
            if key in raw_lower or key in filename_lower:
                return normalized

        # 폴더명이 이미 깔끔하면 그대로 사용
        if raw_maker and raw_maker != "Unknown":
            return raw_maker

        return "Unknown"

    def _register(self, info: ManualInfo) -> None:
        self._all.append(info)
        self._by_filename[info.filename] = info

        maker_key = info.maker.lower()
        if maker_key not in self._by_maker:
            self._by_maker[maker_key] = []
        self._by_maker[maker_key].append(info)

    # ----------------------------------------------------------
    # 조회 API
    # ----------------------------------------------------------
    def find_path(self, filename: str) -> Optional[str]:
        """파일명으로 실제 전체 경로 반환 (대소문자 무시)"""
        info = self._by_filename.get(filename) or self._by_filename.get(filename.lower())
        return info.full_path if info else None

    def find_info(self, filename: str) -> Optional[ManualInfo]:
        return self._by_filename.get(filename) or self._by_filename.get(filename.lower())

    def find_by_maker(self, maker: str) -> List[ManualInfo]:
        """메이커 이름으로 매뉴얼 리스트 반환 (부분 일치 가능)"""
        maker_lower = maker.lower().strip()
        results = []

        # 정확한 키
        if maker_lower in self._by_maker:
            results.extend(self._by_maker[maker_lower])

        # 부분 일치
        for key, items in self._by_maker.items():
            if maker_lower in key or key in maker_lower:
                for item in items:
                    if item not in results:
                        results.append(item)

        return results

    def search(self, keyword: str) -> List[ManualInfo]:
        """파일명 + 메이커 + 경로에서 키워드 검색"""
        keyword = keyword.lower().strip()
        results = []
        for info in self._all:
            if (
                keyword in info.filename.lower()
                or keyword in info.maker.lower()
                or keyword in info.relative_path.lower()
            ):
                results.append(info)
        return results

    def all_manuals(self) -> List[ManualInfo]:
        return self._all.copy()

    def stats(self) -> dict:
        return {
            "total": len(self._all),
            "makers": {k: len(v) for k, v in self._by_maker.items()},
            "manuals_dir": str(self.manuals_dir.resolve()),
        }

    # ----------------------------------------------------------
    # 캐시
    # ----------------------------------------------------------
    def _fingerprint(self) -> dict:
        """폴더의 현재 상태 지문 — 파일 수와 가장 최근 수정 시각.

        캐시에 이 지문을 같이 적어 두고, 다음에 열 때 지금 폴더와 대조한다.
        무효화가 없으면 매뉴얼을 새로 넣어도 옛 목록을 그대로 쓰게 되는데,
        목록에 없으니 "그 매뉴얼은 없다" 는 답이 나가고 이유는 안 보인다.
        """
        n, newest = 0, 0.0
        try:
            for p in self.manuals_dir.rglob("*.pdf"):
                if p.is_file():
                    n += 1
                    newest = max(newest, p.stat().st_mtime)
        except Exception:
            return {"count": -1, "newest": 0.0, "dir": str(self.manuals_dir)}
        return {"count": n, "newest": round(newest, 3),
                "dir": str(self.manuals_dir)}

    def _save_cache(self) -> None:
        try:
            INDEX_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = {"fingerprint": self._fingerprint(),
                       "manuals": [asdict(info) for info in self._all]}
            INDEX_CACHE_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            logger.warning(f"[ManualIndex] 캐시 저장 실패: {e}")

    def _load_cache(self) -> None:
        data = json.loads(INDEX_CACHE_FILE.read_text(encoding="utf-8"))
        # 예전 형식(목록만 든 배열)은 지문이 없으므로 그냥 다시 스캔한다.
        if not isinstance(data, dict):
            raise ValueError("지문 없는 옛 캐시")
        if data.get("fingerprint") != self._fingerprint():
            raise ValueError("폴더가 바뀌었습니다")
        for item in data.get("manuals", []):
            self._register(ManualInfo(**item))


# 전역 싱글톤 (서버에서 편하게 쓰기 위함)
_global_index: Optional[ManualIndex] = None


def get_manual_index(force_rebuild: bool = False) -> ManualIndex:
    global _global_index
    if _global_index is None or force_rebuild:
        _global_index = ManualIndex(force_rebuild=force_rebuild)
    return _global_index


if __name__ == "__main__":
    # 테스트용
    logging.basicConfig(level=logging.INFO)
    idx = ManualIndex(force_rebuild=True)
    print(json.dumps(idx.stats(), ensure_ascii=False, indent=2))

    # 예시 검색
    path = idx.find_path("im_e_sievers-m9-manual_dlm_77020-02.pdf")
    print("Sievers 매뉴얼 경로:", path)

    sievers = idx.find_by_maker("Sievers")
    print(f"Sievers 관련 매뉴얼 {len(sievers)}개")
