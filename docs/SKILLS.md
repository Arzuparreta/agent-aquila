# Skills System - Comprehensive Guide

## Overview

Skills are reusable workflow recipes that the agent can load on demand to perform complex, multi-step tasks. They provide structured, repeatable procedures for common operations like email triage, weekly reviews, and sender management. Skills combine the agent's tool-calling capabilities with step-by-step instructions to create powerful, consistent workflows.

## What is a Skill?

A **skill** is a markdown-based workflow definition that:
- **Describes when to use it**: Clear use cases and trigger conditions
- **Specifies required tools**: Lists the tools and connectors needed
- **Provides step-by-step instructions**: Numbered steps with explicit tool calls
- **Includes best practices**: Tips, traps, and optimization guidelines
- **Handles edge cases**: Guidance for common issues and exceptions

## Skills Architecture

### File Structure

```
backend/skills/
├── gmail-triage/
│   └── SKILL.md
├── silence-sender/
│   └── SKILL.md
├── weekly-review/
│   └── SKILL.md
└── custom-skill/
    └── SKILL.md
```

### System Components

| Layer | Location | Purpose |
|-------|----------|---------|
| **Files** | `backend/skills/<slug>/SKILL.md` | Skill definitions |
| **Service** | `backend/app/services/skills_service.py` | Skill loading and listing |
| **HTTP API** | `GET /skills`, `GET /skills/{slug}` | Web UI access |
| **Agent Tools** | `list_skills`, `load_skill` | Agent skill discovery |
| **Settings UI** | Settings → Skills | User skill management |

### Configuration

**Environment Variable**: `AQUILA_SKILLS_DIR`
- **Default**: `backend/skills/`
- **Purpose**: Override skills directory location
- **Usage**: Set in `.env` or environment for custom skill locations

## SKILL.md Format

### Basic Structure

```markdown
---
name: my-skill
description: One-line summary for the skill list
---

# Skill Title

Detailed description of what this skill does and when to use it.

## When to Use This Skill

Describe the specific scenarios or user requests that should trigger this skill.

## Prerequisites

List any required connectors, tools, or setup needed.

## Steps

1. **First step description**
   - Call `tool_name` with specific parameters
   - Explain what this accomplishes
   - Note any important considerations

2. **Second step description**
   - Call another tool
   - Process the results
   - Handle potential errors

## Best Practices

Tips for getting the most out of this skill.

## Common Issues

Solutions to frequent problems or edge cases.
```

### Frontmatter Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Skill identifier (used as slug if directory name differs) |
| `description` | Yes | One-line summary for skill listings |

### Metadata Extraction

- **Slug**: Directory name (e.g., `gmail-triage`)
- **Title**: Frontmatter `name` or first `# Heading`
- **Summary**: Frontmatter `description` or first paragraph
- **Body**: Markdown content after frontmatter

## Built-in Skills

### Gmail Triage

**Slug**: `gmail-triage`
**Purpose**: Walk through unread Gmail in priority order and decide what to do with each message

**When to Use**:
- User says "triage my inbox"
- User asks "what needs my attention?"
- Part of daily heartbeat automation

**Key Features**:
- Quota-conscious Gmail API usage
- Thread-level processing to minimize API calls
- Urgent vs. actionable vs. noise classification
- Filter suggestions for noise senders

**Tools Used**:
- `gmail_list_messages`
- `gmail_get_thread`
- `gmail_modify_thread`
- `gmail_create_filter`
- `recall_memory`

### Silence Sender

**Slug**: `silence-sender`
**Purpose**: Mute or spam a sender using filters and thread labels

**When to Use**:
- User wants to stop receiving emails from a sender
- User reports spam or unwanted newsletters
- Recurring noise from specific senders

**Key Features**:
- Creates Gmail filters for automatic filtering
- Applies thread labels for organization
- Preserves existing filters
- Conservative approach (requires confirmation)

**Tools Used**:
- `gmail_create_filter`
- `gmail_modify_thread`
- `gmail_list_messages`

### Weekly Review

**Slug**: `weekly-review`
**Purpose**: Structured weekly digest from Gmail + calendar + memory

**When to Use**:
- User requests "weekly review"
- Scheduled heartbeat (e.g., Monday morning)
- Regular status check-ins

**Key Features**:
- Combines multiple data sources
- Structured 5-bullet output format
- Forward-looking and backward-looking summaries
- Actionable insights and recommendations

**Tools Used**:
- `gmail_list_messages`
- `calendar_list_events`
- `recall_memory`
- `upsert_memory`

## Creating Custom Skills

### Step-by-Step Guide

#### 1. Plan Your Skill

**Define the Purpose**:
- What problem does this skill solve?
- When should the agent use it?
- What value does it provide?

**Identify Requirements**:
- Which tools are needed?
- What connectors must be configured?
- Are there any prerequisites?

#### 2. Create the Skill File

```bash
mkdir -p backend/skills/my-custom-skill
touch backend/skills/my-custom-skill/SKILL.md
```

#### 3. Write the Skill Content

```markdown
---
name: my-custom-skill
description: Brief description of what this skill does
---

# My Custom Skill

## When to Use This Skill

Use this skill when the user asks for [specific scenario] or mentions [keywords].

## Prerequisites

- Required connector: [e.g., Gmail, Calendar]
- Required tools: [list specific tools]
- Setup requirements: [any special setup needed]

## Steps

1. **Initial Setup**
   - Call `tool_name` with parameters: `param1=value1, param2=value2`
   - This accomplishes [specific goal]
   - Important: [note any critical considerations]

2. **Main Processing**
   - Process the results from step 1
   - Call `another_tool` with processed data
   - Handle errors gracefully

3. **Finalization**
   - Summarize results for the user
   - Store important information in memory
   - Clean up temporary data

## Best Practices

- Tip 1 for optimal usage
- Tip 2 for avoiding common mistakes
- Tip 3 for getting better results

## Common Issues

**Issue**: Description of common problem
**Solution**: How to resolve it

**Issue**: Another common problem
**Solution**: Alternative approach or workaround
```

#### 4. Test Your Skill

**Manual Testing**:
1. Start the agent
2. Call `list_skills` to verify your skill appears
3. Call `load_skill` with your skill slug
4. Follow the steps manually to verify they work
5. Test edge cases and error conditions

**Automated Testing**:
```python
# backend/tests/test_skills.py
async def test_my_custom_skill():
    skill = load_skill("my-custom-skill")
    assert skill is not None
    assert skill.slug == "my-custom-skill"
    # Add more assertions as needed
```

### Skill Authoring Best Practices

#### Structure and Organization

1. **Clear Purpose**: Start with a concise description of what the skill does
2. **When to Use**: Be specific about trigger conditions and use cases
3. **Logical Flow**: Number steps in the order they should be executed
4. **Tool References**: Explicitly name tools in each step
5. **Error Handling**: Include guidance for handling failures

#### Content Guidelines

1. **Be Specific**: Use concrete examples rather than vague descriptions
2. **Include Parameters**: Specify important tool parameters and values
3. **Note Constraints**: Mention API limits, quotas, or other restrictions
4. **Provide Context**: Explain why each step is necessary
5. **Add Tips**: Include practical advice for optimal results

#### Technical Considerations

1. **Tool Availability**: Ensure all required tools exist and are accessible
2. **Connector Requirements**: Specify which connectors must be configured
3. **Rate Limits**: Note any API rate limits or quotas
4. **Error Recovery**: Provide guidance for handling transient failures
5. **Performance**: Consider efficiency and resource usage

## Skill Examples

### Example 1: Calendar Cleanup

```markdown
---
name: calendar-cleanup
description: Clean up old calendar events and remove duplicates
---

# Calendar Cleanup

## When to Use This Skill

Use this skill when the user wants to clean up their calendar, remove old events, or eliminate duplicates.

## Prerequisites

- Google Calendar connector must be configured
- User must have calendar read/write permissions

## Steps

1. **List Recent Events**
   - Call `calendar_list_events` with `time_min=<30 days ago>` and `max_results=100`
   - This retrieves events from the past month for review
   - Important: Use a reasonable time range to avoid overwhelming the user

2. **Identify Potential Issues**
   - Look for events with similar titles and times (potential duplicates)
   - Identify very old events that might need archiving
   - Note any events with missing information

3. **Propose Cleanup Actions**
   - For duplicates: suggest keeping the most recent version
   - For old events: suggest archiving or deleting
   - For incomplete events: suggest updating or removing

4. **Execute Cleanup**
   - Call `calendar_delete_event` for confirmed deletions
   - Call `calendar_update_event` for confirmed updates
   - Summarize actions taken for the user

## Best Practices

- Always confirm before deleting events
- Archive rather than delete when uncertain
- Focus on recent events first (past 3-6 months)
- Consider event importance before deletion

## Common Issues

**Issue**: Too many events to process
**Solution**: Break into smaller time ranges and process incrementally

**Issue**: Uncertain if events are duplicates
**Solution**: Compare event details (attendees, location, description) before deciding
```

### Example 2: Task Prioritization

```markdown
---
name: task-prioritization
description: Prioritize tasks from multiple sources and create an action plan
---

# Task Prioritization

## When to Use This Skill

Use this skill when the user feels overwhelmed and needs help prioritizing tasks from email, calendar, and other sources.

## Prerequisites

- Gmail connector (for task-related emails)
- Google Tasks connector (for existing tasks)
- Memory system (for context and preferences)

## Steps

1. **Gather Tasks from Email**
   - Call `gmail_list_messages` with `q="task OR todo OR action OR deadline"` and `max_results=20`
   - This finds emails that might contain tasks or action items
   - Important: Review subject lines and snippets to identify actual tasks

2. **Review Existing Tasks**
   - Call `tasks_list_tasks` to get current task lists
   - Identify overdue tasks and upcoming deadlines
   - Note tasks that have been pending for a long time

3. **Check Calendar Commitments**
   - Call `calendar_list_events` with `time_min=<now>` and `time_max=<next 7 days>`
   - Identify time-sensitive commitments and deadlines
   - Note any scheduling conflicts

4. **Recall User Priorities**
   - Call `recall_memory` with `query="priorities OR goals OR focus areas"`
   - This retrieves user-stated priorities and goals
   - Use this context to inform prioritization decisions

5. **Create Prioritized Action Plan**
   - Combine all gathered information
   - Prioritize based on: deadlines, importance, user preferences
   - Create a structured list with categories: Urgent, Important, Backlog

6. **Store Action Plan**
   - Call `upsert_memory` with key `task_prioritization:last_run` and today's date
   - Store the prioritized list for future reference
   - Update any relevant task lists if needed

## Best Practices

- Focus on actionable items (things the user can actually do)
- Consider both urgency and importance when prioritizing
- Be realistic about what can be accomplished
- Provide context for why items are prioritized

## Common Issues

**Issue**: Too many tasks to prioritize effectively
**Solution**: Focus on top 10-15 items and suggest breaking down larger tasks

**Issue**: Unclear about user priorities
**Solution**: Ask clarifying questions about goals and deadlines

**Issue**: Tasks from different sources conflict
**Solution**: Highlight conflicts and ask user to resolve
```

## Advanced Skill Features

### Conditional Logic

Skills can include conditional steps based on results:

```markdown
## Steps

1. **Initial Check**
   - Call `check_condition` tool
   - If result indicates X, proceed to step 2a
   - If result indicates Y, proceed to step 2b

2a. **Path for Condition X**
   - Execute these steps for condition X

2b. **Path for Condition Y**
   - Execute these steps for condition Y
```

### Error Handling

Include guidance for handling errors:

```markdown
## Error Handling

**If `tool_name` fails**:
- Check if the connector is properly configured
- Verify required permissions are granted
- Try alternative approach or suggest manual resolution

**If rate limit exceeded**:
- Wait and retry after appropriate delay
- Consider reducing batch size
- Suggest processing during off-peak hours
```

### Memory Integration

Skills can interact with the memory system:

```markdown
## Memory Integration

**Reading Memory**:
- Call `recall_memory` with relevant queries
- Use retrieved context to inform decisions
- Respect user preferences stored in memory

**Writing Memory**:
- Call `upsert_memory` to store important insights
- Use appropriate key naming conventions
- Set importance levels for critical information
```

## Skill Management

### Listing Skills

**Agent Tool**: `list_skills`

**API Endpoint**: `GET /api/v1/skills`

**Response**:
```json
[
  {
    "slug": "gmail-triage",
    "title": "Gmail Triage",
    "summary": "Walk through unread Gmail in priority order"
  },
  {
    "slug": "weekly-review",
    "title": "Weekly Review",
    "summary": "Structured weekly digest from multiple sources"
  }
]
```

### Loading Skills

**Agent Tool**: `load_skill(slug)`

**API Endpoint**: `GET /api/v1/skills/{slug}`

**Response**:
```json
{
  "slug": "gmail-triage",
  "title": "Gmail Triage",
  "summary": "Walk through unread Gmail in priority order",
  "body": "# Gmail Triage\n\n## When to Use This Skill\n..."
}
```

### Skill Discovery

The agent discovers skills through:

1. **System Prompt**: Skills are mentioned in the agent's system prompt
2. **Tool Calls**: Agent calls `list_skills` to see available skills
3. **Pattern Matching**: Agent matches user requests to skill descriptions
4. **Context Clues**: User intent and conversation context inform skill selection

## Troubleshooting

### Skill Not Appearing

**Symptoms**: Custom skill doesn't appear in `list_skills`

**Solutions**:
1. Verify file is in correct location: `backend/skills/<slug>/SKILL.md`
2. Check file naming (case-sensitive)
3. Ensure valid YAML frontmatter
4. Verify file permissions are readable
5. Check for syntax errors in markdown

### Skill Not Loading

**Symptoms**: `load_skill` returns error or empty content

**Solutions**:
1. Validate YAML frontmatter syntax
2. Check for special characters in frontmatter
3. Ensure markdown content is properly formatted
4. Verify file encoding is UTF-8
5. Check for file corruption or incomplete writes

### Agent Not Using Skill

**Symptoms**: Agent doesn't load or use appropriate skill

**Solutions**:
1. Improve skill description for better matching
2. Add more specific "when to use" criteria
3. Include relevant keywords in description
4. Verify skill addresses the user's actual need
5. Test skill with sample user requests

## Performance Considerations

### Skill Loading Performance

- **Disk I/O**: Skills are read from disk on each call
- **Caching**: Consider implementing caching for frequently-used skills
- **File Size**: Keep skill files concise for faster loading
- **Parsing**: YAML frontmatter parsing adds minimal overhead

### Agent Execution Performance

- **Tool Calls**: Minimize unnecessary tool calls in skills
- **Batching**: Batch operations when possible (e.g., multiple emails)
- **Rate Limits**: Respect API rate limits and quotas
- **Memory**: Be mindful of memory usage for large operations

## Security Considerations

### Skill Validation

- **Input Validation**: Validate all user inputs in skill steps
- **Output Sanitization**: Sanitize outputs before displaying
- **Permission Checks**: Verify user has required permissions
- **Resource Limits**: Enforce reasonable resource limits

### Sensitive Operations

- **Confirmation**: Require user confirmation for destructive actions
- **Logging**: Log all skill executions for audit trail
- **Error Messages**: Avoid exposing sensitive information in errors
- **Data Handling**: Handle sensitive data appropriately

## Best Practices Summary

### For Skill Authors

1. **Be Specific**: Clear, concise descriptions and steps
2. **Test Thoroughly**: Test with various scenarios and edge cases
3. **Document Well**: Include prerequisites, best practices, and troubleshooting
4. **Update Regularly**: Keep skills updated with system changes
5. **Share Knowledge**: Document lessons learned and patterns

### For Skill Users

1. **Understand Scope**: Know what each skill can and cannot do
2. **Provide Context**: Give the agent relevant context when using skills
3. **Review Results**: Always review skill execution results
4. **Provide Feedback**: Report issues or suggest improvements
5. **Customize**: Adapt skills to your specific needs

## Future Enhancements

### Planned Features

- **Skill Parameters**: Allow skills to accept parameters for customization
- **Skill Composition**: Enable skills to call other skills
- **Skill Templates**: Provide templates for common skill patterns
- **Skill Testing**: Built-in skill testing and validation
- **Skill Analytics**: Track skill usage and effectiveness

### Community Contributions

- **Skill Library**: Community-contributed skill repository
- **Skill Sharing**: Easy sharing and discovery of skills
- **Skill Reviews**: Community feedback and improvement suggestions
- **Skill Documentation**: Collaborative documentation and examples

## Conclusion

The Agent Aquila skills system provides a powerful, flexible framework for creating reusable workflows that enhance the agent's capabilities. By following best practices for skill authoring and understanding the system architecture, you can create effective skills that save time, improve consistency, and extend the agent's functionality.

Skills are a key differentiator for Agent Aquila, enabling users to customize and extend the system to meet their specific needs while maintaining the benefits of a structured, well-documented approach to automation.