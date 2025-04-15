from fastapi import APIRouter, Depends, HTTPException
import datetime
from google.cloud.firestore_v1.base_query import FieldFilter
from firebase_config import db
from src.utils import get_current_user, require_access_level
from src.constants import (
    CHAT,
    MODULES,
    AGENT_ID,
    USER_ID,
    VERSION,
    STATUS,
    STATUS_CLOSED,
    STATUS_IN_PROGRESS,
    STARTED_AT,
    COMPLETED_AT,
    ACCESS_LEVEL,
    NAME,
    MANAGER_LEVEL,
    USER_LEVEL,
    CRITERIA,
)

router = APIRouter()


@router.get("/", dependencies=[Depends(require_access_level(USER_LEVEL))])
async def get_analytics(
    current_user: dict = Depends(get_current_user),
):
    """
    Get analytics related to modules and their completion status.

    For users:
    - Shows in-progress modules for the current user
    - Average time taken to complete modules
    - Number of completed modules
    - Modules with highest completion rates

    For managers and admins:
    - Higher-level analytics across all users
    - Overall module completion metrics
    - User engagement statistics
    - Most popular modules
    """
    now = datetime.datetime.utcnow()
    user_id = current_user.get(USER_ID)
    access_level = current_user.get(ACCESS_LEVEL)
    is_admin_or_manager = access_level >= MANAGER_LEVEL

    # Initialize analytics object
    analytics = {
        "user_id": user_id,
        "timestamp": now.isoformat(),
        "user_analytics": {},
    }

    # --- User-level analytics (for all access levels) ---
    # Get all chats for the current user
    user_chats_query = (
        db.collection(CHAT).where(filter=FieldFilter(USER_ID, "==", user_id)).get()
    )

    # Process user's own data
    total_chats = len(user_chats_query)
    completed_chats = 0
    in_progress_chats = 0
    completion_times = []
    modules_engaged = set()
    total_criteria = 0
    passed_criteria = 0

    for chat in user_chats_query:
        chat_data = chat.to_dict()
        current_version = chat_data.get(VERSION)
        current_chat = chat_data[CHAT][str(current_version)]
        status = current_chat.get(STATUS)

        # Track module engagement
        modules_engaged.add(chat_data.get(AGENT_ID))

        # Track criteria progress
        criteria_dict = current_chat.get(CRITERIA, {})
        if criteria_dict:
            chat_total_criteria = len(criteria_dict)
            chat_passed_criteria = sum(1 for value in criteria_dict.values() if value)
            total_criteria += chat_total_criteria
            passed_criteria += chat_passed_criteria

        if status == STATUS_CLOSED:
            completed_chats += 1
            # Calculate completion time if both timestamps exist
            started_at = current_chat.get(STARTED_AT)
            completed_at = current_chat.get(COMPLETED_AT)

            if started_at and completed_at:
                try:
                    # Parse ISO format timestamps
                    start_time = datetime.datetime.fromisoformat(started_at)
                    end_time = datetime.datetime.fromisoformat(completed_at)
                    duration = (
                        end_time - start_time
                    ).total_seconds() / 60  # in minutes
                    completion_times.append(duration)
                except (ValueError, TypeError):
                    # Skip if timestamp parsing fails
                    pass

        elif status == STATUS_IN_PROGRESS:
            in_progress_chats += 1

    # Calculate average completion time
    avg_completion_time = (
        sum(completion_times) / len(completion_times) if completion_times else 0
    )

    # User-level analytics
    analytics["user_analytics"] = {
        "total_modules_attempted": total_chats,
        "completed_modules": completed_chats,
        "in_progress_modules": in_progress_chats,
        "unique_modules_engaged": len(modules_engaged),
        "avg_completion_time_minutes": round(avg_completion_time, 2),
        "completion_rate_percentage": (
            round((completed_chats / total_chats) * 100, 2) if total_chats else 0
        ),
        "total_criteria": total_criteria,
        "passed_criteria": passed_criteria,
        "criteria_completion_rate_percentage": (
            round((passed_criteria / total_criteria) * 100, 2) if total_criteria else 0
        ),
    }

    # --- Manager/Admin-level analytics ---
    if is_admin_or_manager:
        # Get all modules
        all_modules_query = db.collection(MODULES).get()
        all_modules = [doc.to_dict() for doc in all_modules_query]

        # Get all chats
        all_chats_query = db.collection(CHAT).get()
        all_chats = [doc.to_dict() for doc in all_chats_query]

        # Process organization-wide data
        total_org_chats = len(all_chats)
        completed_org_chats = 0
        module_engagement = {}  # Track which modules are most used
        user_engagement = {}  # Track user engagement
        module_completion_rates = {}  # Track module completion rates
        org_completion_times = []

        # Initialize module engagement counters
        for module in all_modules:
            module_id = module.get(AGENT_ID)
            module_name = module.get(NAME, "Unknown")
            module_engagement[module_id] = {
                "module_id": module_id,
                "module_name": module_name,
                "total_attempts": 0,
                "completed": 0,
                "in_progress": 0,
                "total_criteria": 0,
                "passed_criteria": 0,
            }

        # Analyze all chats
        for chat in all_chats:
            user_id = chat.get(USER_ID)
            module_id = chat.get(AGENT_ID)
            current_version = chat.get(VERSION)

            # Skip if missing essential data
            if not (user_id and module_id and current_version and CHAT in chat):
                continue

            current_chat = chat[CHAT][str(current_version)]
            status = current_chat.get(STATUS)

            # Update user engagement
            if user_id not in user_engagement:
                user_engagement[user_id] = {
                    "total_attempts": 0,
                    "completed": 0,
                    "in_progress": 0,
                }

            user_engagement[user_id]["total_attempts"] += 1

            # Update module engagement
            if module_id in module_engagement:
                module_engagement[module_id]["total_attempts"] += 1

                # Track criteria progress
                criteria_dict = current_chat.get(CRITERIA, {})
                if criteria_dict:
                    module_criteria_count = len(criteria_dict)
                    module_passed_criteria = sum(
                        1 for value in criteria_dict.values() if value
                    )
                    module_engagement[module_id][
                        "total_criteria"
                    ] += module_criteria_count
                    module_engagement[module_id][
                        "passed_criteria"
                    ] += module_passed_criteria

                if status == STATUS_CLOSED:
                    module_engagement[module_id]["completed"] += 1
                    user_engagement[user_id]["completed"] += 1
                    completed_org_chats += 1

                    # Calculate completion time
                    started_at = current_chat.get(STARTED_AT)
                    completed_at = current_chat.get(COMPLETED_AT)

                    if started_at and completed_at:
                        try:
                            start_time = datetime.datetime.fromisoformat(started_at)
                            end_time = datetime.datetime.fromisoformat(completed_at)
                            duration = (
                                end_time - start_time
                            ).total_seconds() / 60  # in minutes
                            org_completion_times.append(duration)
                        except (ValueError, TypeError):
                            pass

                elif status == STATUS_IN_PROGRESS:
                    module_engagement[module_id]["in_progress"] += 1
                    user_engagement[user_id]["in_progress"] += 1

        # Calculate module completion rates
        for module_id, data in module_engagement.items():
            if data["total_attempts"] > 0:
                completion_rate = (data["completed"] / data["total_attempts"]) * 100
                module_completion_rates[module_id] = {
                    "module_id": module_id,
                    "module_name": data["module_name"],
                    "completion_rate": round(completion_rate, 2),
                    "total_attempts": data["total_attempts"],
                }

        # Sort modules by completion rate and get top 5
        top_modules = sorted(
            [v for v in module_completion_rates.values() if v["total_attempts"] > 0],
            key=lambda x: x["completion_rate"],
            reverse=True,
        )[:5]

        # Sort modules by total attempts and get top 5
        most_popular_modules = sorted(
            [v for v in module_engagement.values()],
            key=lambda x: x["total_attempts"],
            reverse=True,
        )[:5]

        # Calculate organization-wide metrics
        avg_org_completion_time = (
            sum(org_completion_times) / len(org_completion_times)
            if org_completion_times
            else 0
        )
        org_completion_rate = (
            (completed_org_chats / total_org_chats) * 100 if total_org_chats else 0
        )

        # Calculate total criteria metrics across all modules
        org_total_criteria = sum(
            module["total_criteria"] for module in module_engagement.values()
        )
        org_passed_criteria = sum(
            module["passed_criteria"] for module in module_engagement.values()
        )
        org_criteria_completion_rate = (
            (org_passed_criteria / org_total_criteria) * 100
            if org_total_criteria
            else 0
        )

        # Add organization-wide analytics
        analytics["organization_analytics"] = {
            "total_modules_available": len(all_modules),
            "total_module_sessions": total_org_chats,
            "completed_sessions": completed_org_chats,
            "in_progress_sessions": total_org_chats - completed_org_chats,
            "avg_completion_time_minutes": round(avg_org_completion_time, 2),
            "overall_completion_rate_percentage": round(org_completion_rate, 2),
            "top_completed_modules": top_modules,
            "most_popular_modules": most_popular_modules,
            "total_active_users": len(user_engagement),
            "total_criteria_across_modules": org_total_criteria,
            "passed_criteria_across_modules": org_passed_criteria,
            "criteria_completion_rate_percentage": round(
                org_criteria_completion_rate, 2
            ),
        }

    return analytics
