"""Agent 16 — Application Assistant

Helps users with resume tailoring, statement structure, cover letters,
application checklists, preparation plans, and deadline planning.

IMPORTANT: Never fabricates achievements, projects, awards, grades,
experience, publications, or skills. Can improve wording but must preserve truth.
"""
from src.agents.base import BaseAgent, AgentStatus, AgentCategory, AgentResult, AgentEvidence


class ApplicationAssistant(BaseAgent):
    AGENT_ID = "application_assistant"
    AGENT_NAME = "Application Assistant"
    AGENT_CATEGORY = AgentCategory.USER
    AGENT_DESCRIPTION = "Helps with resume tailoring, cover letters, checklists, and preparation"

    def process(self, input_data: dict) -> AgentResult:
        from src import db

        task = input_data.get("task", "checklist")
        opportunity_id = input_data.get("opportunity_id")
        user_id = input_data.get("user_id")

        result_data = {}

        if task == "checklist" and opportunity_id:
            result_data = self._generate_checklist(opportunity_id)
        elif task == "tailor" and opportunity_id and user_id:
            result_data = self._tailor_resume(opportunity_id, user_id)
        elif task == "preparation" and opportunity_id:
            result_data = self._preparation_plan(opportunity_id)
        elif task == "deadline_plan" and user_id:
            result_data = self._deadline_plan(user_id)
        else:
            result_data = {
                "message": "Please provide the required parameters for this task.",
                "available_tasks": ["checklist", "tailor", "preparation", "deadline_plan"],
            }

        evidence = [
            AgentEvidence(
                field="application_assistance",
                value=task,
                confidence=0.7,
                agent_id=self.AGENT_ID,
            )
        ]

        return AgentResult(
            agent_id=self.AGENT_ID,
            status=AgentStatus.COMPLETED,
            data=result_data,
            confidence=0.7,
            evidence=evidence,
        )

    def _generate_checklist(self, opportunity_id: int) -> dict:
        from src import db

        opp = db.get_opportunity(opportunity_id)
        if not opp:
            return {"error": "Opportunity not found"}

        checklist = [
            {"item": "Review eligibility requirements", "done": False},
            {"item": "Prepare resume/CV", "done": False},
            {"item": "Write statement of purpose", "done": False},
            {"item": "Gather recommendation letters", "done": False},
            {"item": "Prepare transcripts", "done": False},
        ]

        if opp.get("application_url"):
            checklist.append({"item": "Visit application portal", "done": False})
        if opp.get("minimum_gpa"):
            checklist.append({"item": f"Verify GPA meets minimum ({opp['minimum_gpa']})", "done": False})
        if opp.get("preferred_skills"):
            checklist.append({"item": "Highlight relevant skills", "done": False})

        return {
            "opportunity": opp.get("title"),
            "organization": opp.get("organization"),
            "deadline": opp.get("deadline"),
            "checklist": checklist,
        }

    def _tailor_resume(self, opportunity_id: int, user_id: int) -> dict:
        from src import db

        opp = db.get_opportunity(opportunity_id)
        user = db.get_user_by_id(user_id)
        resume = db.get_user_resume(user_id)

        if not opp or not user:
            return {"error": "Opportunity or user not found"}

        suggestions = []
        opp_skills = opp.get("preferred_skills") or []
        user_skills = user.get("skills") or []
        if opp_skills:
            missing = [s for s in opp_skills if s.lower() not in [us.lower() for us in user_skills]]
            if missing:
                suggestions.append(f"Consider highlighting: {', '.join(missing[:5])}")

        return {
            "opportunity": opp.get("title"),
            "suggestions": suggestions,
            "resume_available": bool(resume),
        }

    def _preparation_plan(self, opportunity_id: int) -> dict:
        from src import db

        opp = db.get_opportunity(opportunity_id)
        if not opp:
            return {"error": "Opportunity not found"}

        return {
            "opportunity": opp.get("title"),
            "organization": opp.get("organization"),
            "deadline": opp.get("deadline"),
            "steps": [
                "Research the organization",
                "Review eligibility requirements",
                "Prepare application materials",
                "Practice if interview is required",
                "Submit before deadline",
            ],
        }

    def _deadline_plan(self, user_id: int) -> dict:
        from src import db
        from src.deadlines import days_left

        apps = db.list_applications(user_id)
        upcoming = []
        for app in apps:
            days = days_left(app.get("deadline"))
            if days is not None and 0 <= days <= 30:
                upcoming.append({
                    "title": app.get("title"),
                    "deadline": app.get("deadline"),
                    "days_left": days,
                    "status": app.get("status"),
                })

        upcoming.sort(key=lambda x: x["days_left"])
        return {"upcoming_deadlines": upcoming}
