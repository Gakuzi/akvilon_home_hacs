# Task Schema и формат коммуникации агентов

> **Единый протокол** взаимодействия для всех агентов/субагентов в проекте Akvilon InHome.
> Этот документ обязателен к соблюдению. Любой агент, который ставит задачу другому
> агенту, передаёт эту схему вместе с задачей.

---

## 1. Формат постановки задачи (User -> Orchestrator)

Пользователь отправляет цель в свободной форме. Orchestrator парсит её в структурированный объект.

**Внутреннее представление Orchestrator:**
```json
{
  "goal_id": "GOAL-2026-10-06-001",
  "title": "Реализация фичи X",
  "description": "Описание цели",
  "acceptance_criteria": ["Критерий 1", "Критерий 2"],
  "priority": "high",
  "requested_by": "user"
}
```

## 2. Формат подзадачи (Orchestrator -> Subagent)

Каждая подзадача передается субагенту как строго типизированный объект.

### TASK TEMPLATE
```json
{
  "task_id": "TASK-[ID]",
  "goal_id": "GOAL-[ID]",
  "type": "feature|bugfix|test|review|doc",
  "title": "[Краткое название]",
  "description": "[Полное описание что сделать]",
  "assigned_to": "@agent-[planner|developer|tester|reviewer|documenter]",
  "context": {
    "spec_url": ".github/specs/SPEC-001.md",
    "related_pr": "#123",
    "related_issue": "#456"
  },
  "requirements": ["Требование 1", "Требование 2"],
  "constraints": ["Ограничение 1", "Ограничение 2"],
  "deliverable": ["Файл: src/foo/bar.ts", "Файл: tests/foo/test.ts"],
  "deadline": "2026-10-07T18:00:00Z",
  "status": "pending|in_progress|done|blocked"
}
```

## 3. Формат ответа субагента (Subagent -> Orchestrator)

### SUCCESS RESPONSE
```json
{
  "task_id": "TASK-001",
  "status": "success",
  "message": "Реализовано согласно SPEC. Код покрыт тестами.",
  "artifacts": {
    "files": ["src/auth/google.ts", "tests/auth/google.test.ts"],
    "pr_url": "https://github.com/Gakuzi/akvilon_home/pull/789",
    "coverage": 87
  },
  "next_steps": [{"action": "assign", "agent": "@agent-reviewer", "task_id": "TASK-002"}],
  "timestamp": "2026-10-06T14:30:00Z"
}
```

### BLOCKED RESPONSE
```json
{
  "task_id": "TASK-001",
  "status": "blocked",
  "message": "Описание проблемы, требующей решения.",
  "requires_decision": true,
  "options": [
    {"id": "opt1", "label": "Вариант 1", "pros": "плюс", "cons": "минус"},
    {"id": "opt2", "label": "Вариант 2", "pros": "плюс", "cons": "минус"}
  ],
  "timestamp": "2026-10-06T14:30:00Z"
}
```

### ERROR RESPONSE
```json
{
  "task_id": "TASK-001",
  "status": "error",
  "message": "Описание ошибки.",
  "error_details": {"type": "тип", "detail": "детали"},
  "suggested_fix": "Предлагаемое исправление",
  "timestamp": "2026-10-06T14:30:00Z"
}
```

## 4. Спецификации (SPEC)

Спецификации хранятся в `.github/specs/` и являются **единым источником истины**.
Формат описан в `.github/specs/README.md` (шаблон) и роли Planner.

## 5. Workflow State Machine

```
[User Goal]
    ↓
[Orchestrator: Parse & Decompose]
    ↓
[Planner: Create SPEC] --(SPEC.md)--> [Orchestrator]
    ↓
[Developer: Code] --(PR)--> [Orchestrator]
    ↓
    ├-> [Tester: Tests] --(Report)--> [Orchestrator]
    └-> [Reviewer: Review] --(Approval)--> [Orchestrator]
    ↓
[Documenter: Docs] --(Update)--> [Orchestrator]
    ↓
[Orchestrator: Validate All]
    ↓
[Orchestrator: Merge to develop]
    ↓
[CI/CD: Deploy to Staging]
    ↓
[User/UAT: Acceptance]
    ↓
[Orchestrator: Merge to main (Release)]
```

## 6. Правила эскалации

1. **Level 1 (Auto)**: Субагент пытается решить сам (3 попытки).
2. **Level 2 (Orchestrator)**: Если заблокирован, Orchestrator анализирует и принимает решение.
3. **Level 3 (Human)**: Если Orchestrator не может решить (архитектурный вопрос), задача помечается `needs_human`.

## 7. Роли (краткая карта)

Полные описания — в `.github/roles/*.md`.

| Роль | Вход | Выход |
|------|------|-------|
| **Planner** | задача от Orchestrator | `SPEC-<id>.md` (без кода) |
| **Developer** | SPEC + ветка | PR с кодом и unit-тестами |
| **Tester** | PR + SPEC | отчёт тестов (✅/❌) |
| **Reviewer** | PR + отчёт тестера | Approve / Request Changes |
| **Documenter** | PR + SPEC | обновлённая документация |

## 8. Правила безопасности и секретности

- Никакие реальные личные данные (IP сервера, DeviceID, ServerID, PASS, токены)
  не публикуются в публичный репозиторий. Публикация — только через `sanitize.sh`.
- Подробнее — в `RELEASE_POLICY.md`.

---

**Все агенты обязаны строго следовать данной схеме.**