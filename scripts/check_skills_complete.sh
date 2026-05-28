#!/bin/bash
# Skill completeness audit for .claude/skills/.
#
# 解 finding #16（2026-04-27 .claude/skills/member-questions/SKILL.md 遺失 incident）。
# 用 weekly cron 跑（建議掛在 host crontab Wed 03:00），出 missing/dead-reference 列表。
#
# Usage:
#   bash scripts/check_skills_complete.sh           # 印 report 到 stdout
#   bash scripts/check_skills_complete.sh --json    # JSON 輸出（給 cron 寫 log + 觸 alert）
#
# Exit codes:
#   0 = all clean
#   1 = found missing SKILL.md OR dead references
#   2 = usage error

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_DIR="${ROOT}/.claude/skills"

if [ ! -d "$SKILLS_DIR" ]; then
    echo "error: $SKILLS_DIR not found" >&2
    exit 2
fi

JSON_MODE=0
if [ "${1:-}" = "--json" ]; then
    JSON_MODE=1
fi

missing_skill_md=()
empty_frontmatter=()
dead_references=()
workflow_drift=()
stale_skills=()
STALE_DAYS=30

if [ "${1:-}" = "--stale-days" ]; then
    if [ -z "${2:-}" ] || ! [[ "${2:-}" =~ ^[0-9]+$ ]]; then
        echo "error: --stale-days requires integer days" >&2
        exit 2
    fi
    STALE_DAYS="$2"
    shift 2
elif [ "${2:-}" = "--stale-days" ]; then
    if [ -z "${3:-}" ] || ! [[ "${3:-}" =~ ^[0-9]+$ ]]; then
        echo "error: --stale-days requires integer days" >&2
        exit 2
    fi
    STALE_DAYS="$3"
fi

now_epoch=$(date +%s)
stale_cutoff=$((now_epoch - STALE_DAYS * 86400))

for skill_dir in "$SKILLS_DIR"/*/; do
    [ -d "$skill_dir" ] || continue
    skill_name=$(basename "$skill_dir")
    skill_md="${skill_dir}SKILL.md"

    if [ ! -f "$skill_md" ]; then
        missing_skill_md+=("$skill_name")
        continue
    fi

    # Frontmatter must have at least `name:` and `description:` lines
    if ! grep -q "^name:" "$skill_md" || ! grep -q "^description:" "$skill_md"; then
        empty_frontmatter+=("$skill_name")
    fi

    skill_mtime=$(stat -f "%m" "$skill_md")
    if [ "$skill_mtime" -lt "$stale_cutoff" ]; then
        stale_skills+=("$skill_name")
    fi

    # Find references in SKILL.md，三種形式皆檢查：
    #   form A: `.claude/skills/<other>/references/X.md` (cross-skill full path)
    #   form B: `.agents/skills/<other>/references/X.md` (legacy typo, warn）
    #   form C: 純 `references/X.md` (same-skill relative)
    while IFS= read -r ref_path; do
        [ -z "$ref_path" ] && continue

        # form A: full canonical path
        if [[ "$ref_path" == .claude/skills/* ]]; then
            full_ref="${ROOT}/${ref_path}"
            if [ ! -f "$full_ref" ]; then
                dead_references+=("$skill_name :: $ref_path")
            fi
            continue
        fi

        # form B: legacy `.agents/` path — auto-translate to `.claude/`
        if [[ "$ref_path" == .agents/skills/* ]]; then
            translated="${ref_path/.agents/.claude}"
            full_ref="${ROOT}/${translated}"
            if [ ! -f "$full_ref" ]; then
                dead_references+=("$skill_name :: $ref_path (legacy .agents/ path; .claude/ target also missing)")
            else
                dead_references+=("$skill_name :: $ref_path (legacy .agents/ path — fix to .claude/)")
            fi
            continue
        fi

        # form C: same-skill relative
        local_ref="${skill_dir}${ref_path}"
        if [ ! -f "$local_ref" ]; then
            dead_references+=("$skill_name :: $ref_path")
        fi
    done < <(grep -oE '(\.agents|\.claude)/skills/[a-zA-Z0-9_./-]+\.md|(^|[^a-zA-Z./])references/[a-zA-Z0-9_./-]+\.md' "$skill_md" \
        | sed -E 's/^[^a-zA-Z./]+//' | sort -u)

    while IFS= read -r md_file; do
        [ -f "$md_file" ] || continue
        rel_file="${md_file#$ROOT/}"

        if grep -q 'uv run python -m volpred\.cli ops' "$md_file"; then
            workflow_drift+=("$skill_name :: $rel_file :: legacy ops CLI (uv run python -m volpred.cli ops) -> use uv run volpred ops")
        fi

        if grep -q 'experiments/K{ID}/k{id}_results\.json\|experiments/K{ID}/\|grep "K{ID}' "$md_file"; then
            workflow_drift+=("$skill_name :: $rel_file :: legacy uppercase experiment placeholder (experiments/K{ID}) -> use lowercase experiments/<experiment_id>/")
        fi
    done < <(find "$skill_dir" -type f -name '*.md' | sort)
done

if [ "$JSON_MODE" = "1" ]; then
    # Compose minimal JSON
    printf '{\n'
    printf '  "generated_at": "%s",\n' "$(date -u +%FT%TZ)"
    printf '  "skills_total": %d,\n' "$(ls -1d "$SKILLS_DIR"/*/ 2>/dev/null | wc -l | tr -d ' ')"
    printf '  "missing_skill_md": ['
    for i in "${!missing_skill_md[@]}"; do
        [ "$i" -gt 0 ] && printf ', '
        printf '"%s"' "${missing_skill_md[$i]}"
    done
    printf '],\n'
    printf '  "empty_frontmatter": ['
    for i in "${!empty_frontmatter[@]}"; do
        [ "$i" -gt 0 ] && printf ', '
        printf '"%s"' "${empty_frontmatter[$i]}"
    done
    printf '],\n'
    printf '  "stale_skills": ['
    for i in "${!stale_skills[@]}"; do
        [ "$i" -gt 0 ] && printf ', '
        printf '"%s"' "${stale_skills[$i]}"
    done
    printf '],\n'
    printf '  "dead_references": ['
    for i in "${!dead_references[@]}"; do
        [ "$i" -gt 0 ] && printf ', '
        printf '"%s"' "${dead_references[$i]}"
    done
    printf '],\n'
    printf '  "workflow_drift": ['
    for i in "${!workflow_drift[@]}"; do
        [ "$i" -gt 0 ] && printf ', '
        printf '"%s"' "${workflow_drift[$i]}"
    done
    printf ']\n'
    printf '}\n'
else
    echo "=== Skill Audit @ $(date -u +%FT%TZ) ==="
    echo ""
    skills_total=$(ls -1d "$SKILLS_DIR"/*/ 2>/dev/null | wc -l | tr -d ' ')
    echo "Total skills: $skills_total"
    echo ""

    if [ ${#missing_skill_md[@]} -gt 0 ]; then
        echo "🔴 missing SKILL.md (${#missing_skill_md[@]}):"
        printf '  - %s\n' "${missing_skill_md[@]}"
        echo ""
    else
        echo "✅ all skill dirs have SKILL.md"
    fi

    if [ ${#empty_frontmatter[@]} -gt 0 ]; then
        echo "⚠️  empty/incomplete frontmatter (${#empty_frontmatter[@]}):"
        printf '  - %s\n' "${empty_frontmatter[@]}"
        echo ""
    else
        echo "✅ all SKILL.md have name + description frontmatter"
    fi

    echo "ℹ️  stale threshold: ${STALE_DAYS} day(s)"
    if [ ${#stale_skills[@]} -gt 0 ]; then
        echo "⚠️  stale SKILL.md mtime (${#stale_skills[@]}):"
        printf '  - %s\n' "${stale_skills[@]}"
        echo ""
    else
        echo "✅ no SKILL.md older than ${STALE_DAYS} days"
    fi

    if [ ${#dead_references[@]} -gt 0 ]; then
        echo "🔴 dead references in SKILL.md (${#dead_references[@]}):"
        printf '  - %s\n' "${dead_references[@]}"
        echo ""
    else
        echo "✅ all references/*.md mentions in SKILL.md exist"
    fi

    if [ ${#workflow_drift[@]} -gt 0 ]; then
        echo "🔴 workflow drift patterns (${#workflow_drift[@]}):"
        printf '  - %s\n' "${workflow_drift[@]}"
        echo ""
    else
        echo "✅ no legacy workflow patterns detected"
    fi
fi

# Exit 1 if any issue found
if [ ${#missing_skill_md[@]} -gt 0 ] || [ ${#dead_references[@]} -gt 0 ] || [ ${#workflow_drift[@]} -gt 0 ]; then
    exit 1
fi

exit 0
