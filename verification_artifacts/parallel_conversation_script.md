# Parallel Conversation Stress Script

Purpose: verify Finimatic can keep two active outreach conversations separate, preserve context, generate context-aware replies, and avoid sending the wrong draft to the wrong contact.

Sender persona:
- Name: Ross Dmello
- Role: AI Engineer
- Offer: RAG chatbots, AI automation, and student/support workflow systems for educators and course creators.

Prospect A:
- Email: crce.9955.ce@gmail.com
- Persona: YouTube creator who sells courses.
- Main pain: too many repetitive student questions and low conversion from content viewers to course buyers.

Prospect B:
- Email: rossdmello896@gmail.com
- Persona: school teacher with an online learning website.
- Main pain: needs parent/student support, lesson search, and lightweight automation without technical complexity.

## Prospect A: Course Creator Conversation

1. Ross: Cold opener referencing course content and asking if a RAG assistant could help students find answers and improve course sales.
2. Prospect: Asks what RAG means and whether it is just another chatbot.
3. Ross: Explains RAG in simple terms and asks what students ask most often.
4. Prospect: Says students ask about prerequisites, refunds, certificates, and lesson order.
5. Ross: Suggests a first version that answers FAQ and points to the right lesson; asks where course content lives.
6. Prospect: Says content is split across YouTube, Google Drive PDFs, and a course platform.
7. Ross: Explains how those sources can be indexed; asks whether they want public lead capture or student-only support first.
8. Prospect: Wants lead capture first and asks about cost.
9. Ross: Gives a small pilot scope instead of a hard price; asks for monthly lead volume and course price range.
10. Prospect: Gives rough numbers and asks if it can integrate with WhatsApp.
11. Ross: Explains WhatsApp can be phase two; asks whether email capture is enough for the first pilot.
12. Prospect: Says email capture is fine but worries about hallucinations.
13. Ross: Explains source-grounded answers, unknown fallback, and audit logs; asks if they can share 10 common questions.
14. Prospect: Shares sample questions.
15. Ross: Maps those questions to pilot features and proposes a short call.
16. Prospect: Asks for expected timeline.
17. Ross: Gives 5-7 day pilot timeline and asks for two suitable call times.
18. Prospect: Gives two time slots.
19. Ross: Confirms one slot and summarizes pilot agenda.
20. Prospect: Confirms.

## Prospect B: School Teacher Conversation

1. Ross: Cold opener referencing online teaching and asking if an AI assistant could help students and parents find lesson answers.
2. Prospect: Asks if this is difficult to manage.
3. Ross: Explains low-maintenance setup and asks what the website currently contains.
4. Prospect: Says it has notes, assignments, exam reminders, and parent announcements.
5. Ross: Suggests first version for lesson search and parent FAQ; asks which audience matters more.
6. Prospect: Says parents are the bigger burden.
7. Ross: Recommends parent FAQ assistant; asks what languages parents use.
8. Prospect: Says English plus some Hindi/Marathi.
9. Ross: Explains multilingual answers with source grounding; asks if answers should be formal or friendly.
10. Prospect: Wants simple friendly tone and asks about privacy.
11. Ross: Explains private content handling and no public display of internal notes; asks what documents can be used.
12. Prospect: Says PDFs and Google Docs.
13. Ross: Suggests a document-based pilot and asks if they want a website widget or WhatsApp-style flow.
14. Prospect: Wants website first.
15. Ross: Outlines the first pilot and asks for the top 20 parent questions.
16. Prospect: Provides examples.
17. Ross: Converts them into pilot modules and proposes a short setup call.
18. Prospect: Asks if it can be ready before exams.
19. Ross: Gives a realistic timeline and asks for two suitable times.
20. Prospect: Confirms a time.

## Pass Criteria

- Each contact remains in its own conversation thread.
- Generated replies reference the correct prospect persona and prior replies.
- Switching contacts never carries the other contact's subject or body into the composer.
- Small threads route through Groq when provider is Auto and Groq keys are available.
- Large threads route through Gemini 2.5 Flash when provider is Auto.
- Replies fetched from IMAP append as new inbound messages, not duplicate or overwrite old replies.
- Safety gates still block suppressed, unsubscribed, bounced, paused, outside-window, and over-cap sends.
- Generated replies do not contain fake placeholders such as "[Calendly link]".
