# LetMeFit V1 PRD

- Document status: Draft aligned for V1 discussion
- Version: 0.1
- Last updated: 2026-04-27
- Product type: Health and fitness management agent
- Product boundary: Lifestyle and fitness guidance only, not medical diagnosis or treatment

## 1. Product Summary

LetMeFit is a mobile health and fitness agent that helps users quickly record meals and body metrics through photos and voice, organizes that data into a personal fitness archive, and provides lightweight daily recommendations for weight management and healthy habits.

V1 focuses on reducing the friction of logging and increasing the usefulness of daily feedback. It is not intended to replace a doctor, dietitian, or coach.

## 2. Background and Problem Statement

Users who want to lose weight or manage body composition often understand the value of food logging and trend tracking, but fail to sustain the habit because:

- Manual logging is tedious
- Body weight and body fat records are scattered across devices and notes
- Users do not know whether they are eating in line with their goals
- Existing tools often provide dashboards without clear daily action guidance

This product aims to solve the gap between "I know I should track" and "I can actually keep tracking every day."

## 3. Product Goal

The V1 goal is to help general adult users complete a daily loop of:

`Capture -> Extract -> Confirm -> Archive -> Summarize -> Recommend`

The product should make it easy for users to:

- record meals through photo or voice
- record body weight and body fat through scale photos
- correct AI recognition errors quickly
- accumulate a continuous personal fitness archive
- receive simple, practical daily guidance

## 4. Non-Goals

V1 will not attempt to:

- provide medical diagnosis, treatment, or disease management
- support pregnancy, minors, eating disorder cases, or special clinical populations
- generate advanced periodized workout plans
- integrate directly with Bluetooth smart hardware
- build a social network, leaderboard, marketplace, or coach portal
- replace professional nutrition counseling

## 5. Target Users

### 5.1 Primary user segment

- Adults aged 20-40
- General healthy users seeking fat loss or weight management
- Users willing to use photos and voice to reduce manual entry
- Users who want practical guidance but do not want complex data entry

### 5.2 Excluded users in V1

- Minors
- Pregnant users
- Users seeking medical nutrition therapy
- Users with disease-specific dietary management needs
- Users expecting professional bodybuilding or advanced athletic coaching

## 6. Product Positioning

LetMeFit is a fitness management assistant, not a medical app and not a generic chatbot.

The value proposition is:

- lower the cost of daily logging
- improve record continuity
- convert raw records into lightweight actions
- personalize future recognition through user corrections

## 7. Core User Scenarios

### Scenario A: Meal logging by photo

The user takes a photo of a meal. The system identifies likely foods, portion estimates, calories, and macronutrients. The user confirms or edits the result. The meal is then stored in the daily archive.

### Scenario B: Meal logging by voice

The user says something like "For lunch I had chicken salad and a sugar-free latte." The system converts the utterance into structured food items, estimated portions, and nutrition values. The user confirms or edits the result before saving.

### Scenario C: Body metric logging by scale photo

The user takes a photo of a weight scale or body fat scale. The system extracts numeric values such as weight and body fat percentage. The user can edit the result by text or voice, and the corrected result becomes the official record.

### Scenario D: Daily summary and guidance

At the end of the day, the user sees a concise summary of intake, logging completeness, weight trend, and one or more actionable suggestions for the next meal or next day.

## 8. V1 Scope

### 8.1 In scope

- user onboarding with basic profile setup
- goal setting for weight management
- meal logging by photo
- meal logging by voice
- scale photo recognition for weight
- scale photo recognition for body fat metrics
- recognition result confirmation and editing
- daily archive for meals and body metrics
- daily summary generation
- lightweight food and habit recommendations
- user-level correction memory for future improvement

### 8.2 Out of scope

- week-level or month-level fully automated training plans
- direct food barcode scanning
- device integrations such as Apple Health write-back in V1
- smartwatch integrations
- social and gamification features
- advanced coaching personas

## 9. V1 Experience Principles

- The home screen should primarily answer: "What is my status today?"
- Logging should be fast and visible from the first screen
- AI output must always be easy to correct
- Suggestions should be short, concrete, and safe
- The product should reward completion, not overwhelm with analytics

## 10. Functional Requirements

### FR-1 Onboarding and profile

The system shall allow the user to create and edit a basic profile including:

- age
- sex
- height
- current weight
- target weight
- activity level
- primary goal such as fat loss or maintenance

### FR-2 Meal capture

The system shall allow the user to record meals by:

- taking a meal photo
- speaking a meal description
- optionally editing the final structured output before saving

### FR-3 Body metric capture

The system shall allow the user to:

- capture a weight scale image
- capture a body fat scale image
- review and edit extracted values before saving

### FR-4 Confirmation and correction

The system shall:

- display extracted fields clearly
- allow field-level editing
- support text-based or voice-based correction
- persist the corrected value as the official record

### FR-5 Daily archive

The system shall maintain a daily archive containing:

- meals
- body metrics
- summary totals

### FR-6 Daily summary

The system shall produce a summary containing:

- total estimated calorie intake
- protein and macronutrient overview
- logging completeness indication
- recent weight trend snapshot
- one to three practical suggestions

### FR-7 Agent memory

The system shall retain user-specific correction patterns, including:

- common food aliases
- common portion assumptions
- preferred interpretation of repeated expressions
- recurring correction patterns for specific foods or devices

## 11. Recommendation System Requirements

The recommendation system in V1 is a guidance engine, not a predictive ML recommendation platform.

### 11.1 Inputs

- user profile
- stated goal
- meals recorded today
- body metric trends
- user memory and correction history

### 11.2 Output types

- meal timing suggestions
- calorie control suggestions
- protein intake reminders
- hydration or activity reminders
- cautionary prompts when behavior appears too aggressive

### 11.3 Rules and safety boundaries

- Recommendations must be framed as suggestions, not prescriptions
- Recommendations must remain within general wellness scope
- The system must avoid extreme calorie restriction suggestions
- The system must degrade safely when data confidence is low
- The system must provide editable and reviewable outputs

### 11.4 Recommendation generation approach for V1

V1 recommendations should be generated through:

- structured nutrition and trend calculations
- explicit rules and guardrails
- user-specific memory retrieval
- natural language formatting by an LLM layer

The LLM should not be the sole source of decision logic.

## 12. AI Extraction Requirements

### 12.1 Photo understanding

The system should extract likely meal components from food images and extract numeric body metrics from scale photos.

### 12.2 Voice understanding

The system should convert voice input into text and then into structured record candidates.

### 12.3 Confidence handling

The system should preserve confidence indicators internally and use them to decide whether to ask for user confirmation more explicitly.

## 13. Knowledge System Requirements

V1 requires a lightweight vertical knowledge system rather than a standalone knowledge platform.

### 13.1 Required knowledge assets

- food and nutrition reference data
- common serving assumptions
- basic goal templates such as fat loss and maintenance
- recommendation rules
- safety boundary rules

### 13.2 Not required in V1

- large-scale unstructured knowledge retrieval
- standalone RAG platform
- separate vector database as a prerequisite

## 14. User Memory Requirements

User memory is distinct from general knowledge.

It should store:

- food labels the user commonly uses
- repeated correction patterns
- likely defaults for repeated meals
- interpretation preferences for recurring language

Memory should improve future extraction, but users must remain able to override any suggestion.

## 15. Core Data Objects

### 15.1 UserProfile

- user_id
- age
- sex
- height_cm
- current_weight_kg
- target_weight_kg
- activity_level
- goal_type

### 15.2 MealRecord

- meal_id
- user_id
- timestamp
- input_mode
- source_photo_uri
- source_text
- extracted_items
- estimated_calories
- estimated_macros
- confidence
- user_confirmed

### 15.3 BodyMetricRecord

- record_id
- user_id
- timestamp
- source_photo_uri
- weight_kg
- body_fat_pct
- muscle_mass_kg
- confidence
- user_confirmed

### 15.4 CorrectionRecord

- correction_id
- user_id
- record_type
- original_value
- corrected_value
- correction_mode
- timestamp

### 15.5 DailySummary

- summary_id
- user_id
- date
- calorie_total
- macro_total
- logging_completeness_score
- trend_snapshot
- recommendation_output

### 15.6 UserMemory

- memory_id
- user_id
- memory_type
- trigger_pattern
- preferred_mapping
- usage_count
- last_used_at

## 16. Privacy and Safety Requirements

- The product must clearly communicate that it provides general fitness and lifestyle guidance only
- Sensitive health-related user data must be handled with explicit consent and privacy disclosure
- Users must be able to review and correct AI-extracted values before they become authoritative
- The product must avoid implying medical accuracy where such accuracy is not guaranteed
- High-risk or unsupported cases should trigger limitation messaging rather than stronger advice

## 17. Success Metrics

### 17.1 Activation

- percent of new users who complete onboarding
- percent of new users who log at least two records on day 1

### 17.2 Efficiency

- median time to complete a meal record
- median time to complete a body metric record

### 17.3 Quality

- percent of AI results accepted without modification
- percent of records saved after AI extraction

### 17.4 Retention

- day-7 logging retention
- number of active logging days per user per week

### 17.5 Recommendation usefulness

- user-rated helpfulness of daily suggestions
- percent of users who open the daily summary

## 18. Release Assumptions for V1

Unless revised later, this PRD assumes:

- mobile-first product form
- iOS-first launch is recommended
- cloud-backed storage for persistent archive
- local app cache for speed and draft handling

## 19. Milestone Proposal

### Phase 0: Product validation

- finalize PRD
- define information architecture
- create low-fidelity Figma flows

### Phase 1: Prototype

- clickable prototype
- mocked AI extraction flow
- usability review of logging and confirmation

### Phase 2: Build V1

- onboarding
- record capture
- extraction confirmation
- archive
- daily summary
- lightweight recommendation engine

## 20. Open Questions

- Which nutrition data source should be adopted for V1
- Whether workout logging is included in the first public test or delayed
- Whether Apple Health integration is included in V1.1 instead of V1
- What level of explanation should accompany each recommendation

## 21. Definition of Done for V1 Scope Lock

The V1 scope is considered locked when:

- target user segment is confirmed
- in-scope and out-of-scope lists are accepted
- the core daily loop is accepted
- recommendation boundaries are accepted
- required data objects are accepted
- the next step can move into Figma flow design and technical architecture
