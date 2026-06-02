from __future__ import annotations

from app.schemas.mobile_jd import TargetPlatform


PLATFORM_LINKS: dict[TargetPlatform, dict[str, str]] = {
    "generic": {
        "name": "Nền tảng tuyển dụng",
        "url": "https://parse-jd.vercel.app/",
    },
    "parse_jd": {
        "name": "Parse JD",
        "url": "https://parse-jd.vercel.app/",
    },
    "topcv": {
        "name": "TopCV",
        "url": "https://www.topcv.vn/",
    },
    "vietnamworks": {
        "name": "VietnamWorks",
        "url": "https://www.vietnamworks.com/",
    },
    "linkedin": {
        "name": "LinkedIn Jobs",
        "url": "https://www.linkedin.com/jobs/",
    },
}


def get_platform_info(target_platform: TargetPlatform) -> dict[str, str]:
    return PLATFORM_LINKS.get(target_platform, PLATFORM_LINKS["generic"])
