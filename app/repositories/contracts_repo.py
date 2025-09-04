from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

async def update_contract_file_url_and_user(
    session: AsyncSession,
    contract_id: str,
    file_key: str,
    user_id: Optional[int] = None,
) -> int:
    """
    Persist S3 key to contracts.s3_file_key; optionally set contracts.user_id.
    Commits the transaction and returns number of affected rows.
    """
    if user_id is not None:
        result = await session.execute(
            text(
                """
                UPDATE contracts
                SET s3_file_key = :k,
                    user_id  = COALESCE(:uid, user_id)
                WHERE id = :cid
                """
            ),
            {"k": file_key, "uid": user_id, "cid": contract_id},
        )
    else:
        result = await session.execute(
            text(
                """
                UPDATE contracts
                SET s3_file_key = :k
                WHERE id = :cid
                """
            ),
            {"k": file_key, "cid": contract_id},
        )
    await session.commit()
    return result.rowcount
