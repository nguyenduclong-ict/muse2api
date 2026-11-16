---
name: clean-ui-naming
description: Enforce clean, single-language naming in frontend development, UI design, components, and documentation. Use when generating, reviewing, or refactoring UI code, labels, forms, tables, i18n localization keys, or frontend schemas to strictly prevent redundant bilingual glosses like Name (English Name).
---

# Clean UI Naming

Enforce clean, production-grade naming conventions in frontend code, schemas, and user-facing text by strictly banning redundant bilingual parentheses/glosses.

## When to Use

- Generating UI components, forms, tables, modals, or pages.
- Writing or refactoring i18n / localization dictionaries and translation keys.
- Designing schema models, database fields, or form validation schemas (Zod, Yup, etc.).
- Writing SRS, UI specifications, or design system documentation.

## Core Rules

### 1. Ban Bilingual Parentheses / Redundant Glosses

- **Strictly forbidden**: `Tiếng Việt (English Name)` or `English (Tiếng Việt)`.
- **Bad**: `Nội Dung Câu Chuyện (Story Text)`, `Cài đặt (Settings)`, `Xác nhận (Confirm)`, `Họ và tên (Full Name)`.
- **Good**: Choose exactly one language per layer:
  - Vietnamese UI: `Nội dung câu chuyện`, `Cài đặt`, `Xác nhận`, `Họ và tên`.
  - English UI: `Story Text`, `Settings`, `Confirm`, `Full Name`.

### 2. Strict Boundary: Code vs Display Text

- **Source Code Identifiers** (Components, variables, props, hooks, state, types):
  - 100% standard English in `camelCase`, `PascalCase`, or `SCREAMING_SNAKE_CASE`.
  - Example: `storyText`, `StoryTextEditor`, `isConfirmed`, `userProfile`.
  - Never mix Vietnamese pinyin or hybrid words into code identifiers (e.g. avoid `noiDungStory`, `btnXacNhan`).
- **Display Text / UI**:
  - Keep 100% in the target interface language.
  - If using i18n, reference localization keys (e.g., `t('story.content')`) instead of embedding bilingual strings into fallbacks.

### 3. Jargon & Loanwords

- Do not append English definitions to recognized tech terms in parentheses.
  - Bad: `Đăng nhập qua OTP (Mã xác thực một lần)`, `Tải lên qua Dashboard (Bảng điều khiển)`.
  - Good: Use standard industry loanwords directly (`OTP`, `Dashboard`, `Token`) or natural Vietnamese equivalents (`Bảng điều khiển`), never both together.
