from __future__ import annotations

from typing import Any

from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import serialize, sorted_docs


def get_user_templates(user: AuthenticatedUser) -> list[dict[str, Any]]:
    docs = list(repo.jd_templates().where("uid", "==", user.uid).stream())
    ordered = sorted_docs(docs, "updatedAt")
    unique = []
    seen_names: set[str] = set()
    for doc in ordered:
        data = doc.to_dict() or {}
        name = str(data.get("name") or "")
        if name in seen_names:
            continue
        seen_names.add(name)
        unique.append({"id": doc.id, **serialize(data)})
    return unique


def create_template(user: AuthenticatedUser, payload: dict[str, Any]) -> dict[str, Any]:
    doc_ref = repo.create_document(repo.jd_templates())
    doc_ref.set(
        {
            "uid": user.uid,
            "name": str(payload.get("name") or ""),
            "category": str(payload.get("category") or ""),
            "jobPosition": str(payload.get("jobPosition") or ""),
            "jdText": str(payload.get("jdText") or ""),
            "hardFilters": payload.get("hardFilters") or {},
            "createdAt": repo.server_timestamp(),
            "updatedAt": repo.server_timestamp(),
        }
    )
    snapshot = doc_ref.get()
    return {"id": doc_ref.id, **serialize(snapshot.to_dict() or {})}


def update_template(user: AuthenticatedUser, template_id: str, updates: dict[str, Any]) -> bool:
    snapshot = repo.jd_templates().document(template_id).get()
    if not snapshot.exists or (snapshot.to_dict() or {}).get("uid") != user.uid:
        return False

    allowed_fields = {"name", "category", "jobPosition", "jdText", "hardFilters"}
    clean_updates = {
        key: value
        for key, value in updates.items()
        if key in allowed_fields and value is not None
    }
    repo.jd_templates().document(template_id).set(
        {**clean_updates, "updatedAt": repo.server_timestamp()},
        merge=True,
    )
    return True


def delete_template(user: AuthenticatedUser, template_id: str) -> bool:
    snapshot = repo.jd_templates().document(template_id).get()
    if not snapshot.exists or (snapshot.to_dict() or {}).get("uid") != user.uid:
        return False
    snapshot.reference.delete()
    return True


def seed_default_templates_if_empty(user: AuthenticatedUser) -> int:
    if get_user_templates(user):
        return 0

    defaults = [
        {
            "name": "Frontend Developer (React)",
            "category": "IT/Software",
            "jobPosition": "Frontend Developer",
            "jdText": "- Phát triển ứng dụng React/TypeScript.\n- Tối ưu hiệu năng và UX.\n- Tích hợp API với backend.\n- Viết test và review code.",
            "hardFilters": {"location": "Hà Nội", "minExp": "2", "industry": "IT", "salaryMin": "15000000", "salaryMax": "30000000"},
        },
        {
            "name": "Backend Developer (Node.js)",
            "category": "IT/Software",
            "jobPosition": "Backend Developer",
            "jdText": "- Xây dựng RESTful API/GraphQL.\n- Thiết kế database.\n- Đảm bảo bảo mật và hiệu năng.\n- Tích hợp dịch vụ bên thứ ba.",
            "hardFilters": {"location": "Hồ Chí Minh", "minExp": "3", "industry": "IT", "salaryMin": "25000000", "salaryMax": "45000000"},
        },
        {
            "name": "Marketing Executive",
            "category": "Marketing",
            "jobPosition": "Marketing Executive",
            "jdText": "- Triển khai digital marketing.\n- Tối ưu ngân sách quảng cáo.\n- Theo dõi ROI/ROAS.\n- Phối hợp team design và sales.",
            "hardFilters": {"location": "Hà Nội", "minExp": "1", "industry": "Marketing/Advertising", "salaryMin": "10000000", "salaryMax": "15000000"},
        },
    ]
    for item in defaults:
        create_template(user, item)
    return len(defaults)
