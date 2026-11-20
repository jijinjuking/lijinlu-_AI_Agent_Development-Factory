"""
W29-30: AI Marketplace — 评分与评价系统

管理用户评分和评价，提供聚合统计。
"""

from __future__ import annotations

from datetime import datetime

from app.runtime.marketplace.models import MarketplacePackage, PackageRating


class RatingSystem:
    """评分系统

    - 每个用户对每个包最多一条评分
    - 评分范围 1.0 - 5.0，步进 0.5
    - 自动更新 MarketPackage 的 average_rating + rating_count
    """

    MIN_SCORE = 1.0
    MAX_SCORE = 5.0

    def __init__(self):
        self._ratings: dict[str, PackageRating] = {}                          # rating_id -> rating
        self._by_package: dict[str, list[str]] = {}                           # package_id -> [rating_id]
        self._by_user_package: dict[tuple[str, str], str] = {}                # (user_id, package_id) -> rating_id

    # ── 评分操作 ────────────────────────────────────────────────────────────

    async def submit_rating(
        self,
        package: MarketplacePackage,
        user_id: str,
        score: float,
        title: str = "",
        review: str = "",
    ) -> PackageRating:
        """提交或更新评分

        若用户已对该包评分，则更新；否则新增。
        评分必须是 1.0-5.0，步进 0.5。
        """
        # 校验评分
        if score < self.MIN_SCORE or score > self.MAX_SCORE:
            raise ValueError(f"Score must be between {self.MIN_SCORE} and {self.MAX_SCORE}")
        if (score * 10) % 5 != 0:
            raise ValueError("Score must be in 0.5 increments")

        key = (user_id, package.package_id)
        existing_rating_id = self._by_user_package.get(key)

        if existing_rating_id:
            existing = self._ratings[existing_rating_id]
            existing.score = score
            existing.title = title
            existing.review = review
            existing.updated_at = datetime.now()
            rating = existing
        else:
            rating = PackageRating(
                package_id=package.package_id,
                user_id=user_id,
                score=score,
                title=title,
                review=review,
            )
            self._ratings[rating.rating_id] = rating
            if package.package_id not in self._by_package:
                self._by_package[package.package_id] = []
            self._by_package[package.package_id].append(rating.rating_id)
            self._by_user_package[key] = rating.rating_id

        # 更新聚合统计
        await self._recalc_package_rating(package)
        return rating

    async def delete_rating(
        self, rating_id: str, package: MarketplacePackage
    ) -> bool:
        """删除一条评分"""
        rating = self._ratings.pop(rating_id, None)
        if rating is None:
            return False

        # 清理索引
        key = (rating.user_id, rating.package_id)
        self._by_user_package.pop(key, None)

        if rating.package_id in self._by_package:
            self._by_package[rating.package_id].remove(rating_id)
            if not self._by_package[rating.package_id]:
                del self._by_package[rating.package_id]

        await self._recalc_package_rating(package)
        return True

    # ── 查询 ────────────────────────────────────────────────────────────────

    def get_rating(self, rating_id: str) -> PackageRating | None:
        return self._ratings.get(rating_id)

    def get_user_rating(self, user_id: str, package_id: str) -> PackageRating | None:
        key = (user_id, package_id)
        rid = self._by_user_package.get(key)
        if rid:
            return self._ratings.get(rid)
        return None

    def get_package_ratings(
        self, package_id: str, limit: int = 50, offset: int = 0
    ) -> list[PackageRating]:
        """获取包的所有评分，按时间倒序"""
        rating_ids = self._by_package.get(package_id, [])
        ratings = [self._ratings[rid] for rid in rating_ids if rid in self._ratings]
        ratings.sort(key=lambda r: r.created_at, reverse=True)
        return ratings[offset:offset + limit]

    def get_package_rating_count(self, package_id: str) -> int:
        return len(self._by_package.get(package_id, []))

    def get_package_average_rating(self, package_id: str) -> float:
        """获取包的平均评分"""
        rating_ids = self._by_package.get(package_id, [])
        if not rating_ids:
            return 0.0
        total = sum(self._ratings[rid].score for rid in rating_ids if rid in self._ratings)
        count = len(rating_ids)
        return round(total / count, 2) if count > 0 else 0.0

    # ── 统计 ────────────────────────────────────────────────────────────────

    def get_rating_distribution(self, package_id: str) -> dict[int, int]:
        """评分分布 {1: count, 2: count, ..., 5: count}"""
        distribution = {i: 0 for i in range(1, 6)}
        rating_ids = self._by_package.get(package_id, [])
        for rid in rating_ids:
            rating = self._ratings.get(rid)
            if rating:
                bucket = int(rating.score)
                distribution[bucket] = distribution.get(bucket, 0) + 1
        return distribution

    # ── 内部 ────────────────────────────────────────────────────────────────

    async def _recalc_package_rating(self, package: MarketplacePackage):
        """重新计算包的平均评分和评分数量"""
        rating_ids = self._by_package.get(package.package_id, [])
        valid_ratings = [self._ratings[rid] for rid in rating_ids if rid in self._ratings]
        package.rating_count = len(valid_ratings)
        if valid_ratings:
            package.average_rating = round(
                sum(r.score for r in valid_ratings) / len(valid_ratings), 2
            )
        else:
            package.average_rating = 0.0
