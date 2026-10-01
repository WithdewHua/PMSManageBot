"""副作用必须落在 service / jobs / notifications 边界之外的事务外。

repository 只做数据写入；Telegram 发送、群播报、勋章授予与调度提交一律
发生在 repository 返回（事务已提交）之后，由 service、jobs 或 notifications
承担。这些断言是静态的层序护栏，运行时的「副作用失败不回滚已提交状态」
由 `tests/test_blackjack_service_workflows.py` 覆盖。
"""

from __future__ import annotations

import ast
from pathlib import Path

BLACKJACK = Path(__file__).parents[2] / "src/app/domains/blackjack"

REPOSITORY_MODULES = sorted((BLACKJACK / "repository").glob("*.py"))
INTERFACE_AND_SERVICE_MODULES = sorted(
    [
        *BLACKJACK.glob("*.py"),
        *(BLACKJACK / "router").glob("*.py"),
        *(BLACKJACK / "jobs").glob("*.py"),
        *(BLACKJACK / "notifications").glob("*.py"),
    ]
)

# repository 内不得出现的副作用来源（勋章查询/授予经由 service 或 _tx helper，
# 领域模型导入属于跨域基线债务，不在此断言范围）
FORBIDDEN_SIDE_EFFECT_MODULES = (
    "app.integrations.telegram.messaging",
    "app.core.scheduler",
    "app.domains.blackjack.notifications",
    "app.domains.badge_awards",
    "app.domains.badges.service",
)
FORBIDDEN_SIDE_EFFECT_CALLS = (
    "send_message_by_url",
    "schedule_task",
    "schedule_named_task",
    "add_async_job",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _called_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            names.add(func.attr)
        elif isinstance(func, ast.Name):
            names.add(func.id)
    return names


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_repository_modules_contain_no_side_effects() -> None:
    assert REPOSITORY_MODULES
    for path in REPOSITORY_MODULES:
        tree = _tree(path)
        imported = _imported_modules(tree)
        offending_imports = sorted(
            module
            for module in imported
            if module.startswith(FORBIDDEN_SIDE_EFFECT_MODULES)
        )
        called = _called_names(tree) & set(FORBIDDEN_SIDE_EFFECT_CALLS)
        assert offending_imports == [], f"{path.name}: {offending_imports}"
        assert called == set(), f"{path.name}: {sorted(called)}"


def test_scheduler_submissions_stay_in_the_jobs_layer() -> None:
    submitters = {
        path.name
        for path in INTERFACE_AND_SERVICE_MODULES
        if any(
            module == "app.core.scheduler" or module.startswith("app.core.scheduler.")
            for module in _imported_modules(_tree(path))
        )
    }
    # 一次性超时任务的提交在 service（`schedule_blackjack_timeout`），
    # 其余调度注册集中在 app.schedule
    assert submitters == {"service.py"}


def test_routers_do_not_send_notifications_themselves() -> None:
    """router 不直接向 Telegram 发消息：通知由 service / jobs / notifications 发。"""

    for path in sorted((BLACKJACK / "router").glob("*.py")):
        called = _called_names(_tree(path))
        assert "send_message_by_url" not in called, path.name
        assert "_broadcast_group" not in called, path.name
        assert "send_message" not in called, path.name


def test_notifications_are_not_imported_by_service_transactions_owner() -> None:
    """service 只依赖 notifications 模块；repository 不依赖任何通知模块。"""

    assert not any(
        "app.integrations.telegram.messaging" in _imported_modules(_tree(path))
        for path in REPOSITORY_MODULES
    )


def test_tick_runs_the_phases_in_the_documented_order() -> None:
    """报名截止 → 完赛提醒 → 完赛结算：阶段顺序是行为的一部分。"""

    tick = next(
        node
        for node in ast.walk(_tree(BLACKJACK / "service.py"))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "tick_tournaments"
    )
    order = []
    for node in ast.walk(tick):
        if not isinstance(node, ast.Tuple) or len(node.elts) != 3:
            continue
        label, handler = node.elts[0], node.elts[1]
        if isinstance(label, ast.Constant) and isinstance(handler, ast.Name):
            order.append((label.value, handler.id))
    assert order == [
        ("报名截止", "_tick_registration_deadlines"),
        ("完赛提醒", "_tick_completion_reminders"),
        ("完赛结算", "_tick_play_deadlines"),
    ]


def test_tournament_admin_endpoints_keep_auth_and_admin_checks() -> None:
    """管理端点的鉴权与管理员校验不得在迁移中丢失。"""

    tree = _tree(BLACKJACK / "router/tournament_admin.py")
    endpoints = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
        and any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "router"
            for decorator in node.decorator_list
        )
    ]
    assert endpoints
    for node in endpoints:
        decorators = {
            decorator.id
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Name)
        }
        assert "require_telegram_auth" in decorators, node.name
        admin_calls = [
            child
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "check_admin_permission"
        ]
        assert admin_calls, node.name


def _call_line(path: Path, function: str, call: str) -> int:
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        if node.name != function:
            continue
        lines = [
            child.lineno
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and (
                (isinstance(child.func, ast.Name) and child.func.id == call)
                or (isinstance(child.func, ast.Attribute) and child.func.attr == call)
            )
        ]
        assert lines, f"{function} does not call {call}"
        return min(lines)
    raise AssertionError(f"{path.name} has no {function}")


def test_tournament_notifications_run_after_the_committing_calls() -> None:
    service = BLACKJACK / "service.py"
    ordered_pairs = (
        (
            "_tick_registration_deadlines",
            "start_blackjack_tournament",
            "notify_tournament_started",
        ),
        ("_tick_registration_deadlines", "cancel_blackjack_tournament", "_send_many"),
        (
            "_tick_play_deadlines",
            "force_settle_tournament_hands",
            "settle_blackjack_tournament",
        ),
        (
            "_tick_play_deadlines",
            "settle_blackjack_tournament",
            "award_blackjack_champion_badge",
        ),
        ("_tick_play_deadlines", "settle_blackjack_tournament", "_send_many"),
        ("_tick_play_deadlines", "settle_blackjack_tournament", "_broadcast_group"),
    )
    for function, before, after in ordered_pairs:
        before_line = _call_line(service, function, before)
        after_line = _call_line(service, function, after)
        assert before_line < after_line, f"{function}: {before} must precede {after}"
