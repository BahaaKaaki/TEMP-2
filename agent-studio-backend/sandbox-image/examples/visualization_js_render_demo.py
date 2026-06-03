"""
Example: Custom JavaScript render function.

Demonstrates the escape hatch — write arbitrary React.createElement
calls to render fully custom visualizations.  The JS function receives
`data` (the clean output payload) and `React`.

Useful when the built-in DSL primitives don't cover a specific layout.
"""
from agent_studio import output

project_data = {
    "project": "Phoenix Migration",
    "status": "In Progress",
    "completion": 72,
    "phases": [
        {"name": "Discovery", "progress": 100, "color": "#10b981"},
        {"name": "Design", "progress": 100, "color": "#10b981"},
        {"name": "Development", "progress": 85, "color": "#3b82f6"},
        {"name": "Testing", "progress": 40, "color": "#f59e0b"},
        {"name": "Deployment", "progress": 0, "color": "#e5e7eb"},
    ],
    "risks": [
        {"id": "R1", "title": "API compatibility", "severity": "High", "owner": "Backend Team"},
        {"id": "R2", "title": "Data migration volume", "severity": "Medium", "owner": "DBA Team"},
        {"id": "R3", "title": "Vendor timeline", "severity": "Low", "owner": "PM"},
    ],
    "team": [
        {"name": "Alice", "role": "Tech Lead", "tasks": 12},
        {"name": "Bob", "role": "Backend", "tasks": 8},
        {"name": "Carol", "role": "Frontend", "tasks": 15},
        {"name": "Dan", "role": "QA", "tasks": 6},
    ],
}

# Mix DSL primitives with a custom JS render function
output.data(
    data=project_data,
    title="Project Dashboard",
    visualization=[
        {
            "type": "header",
            "title": "Phoenix Migration Dashboard",
            "badges": {"status": "In Progress", "completion": "72%"},
        },
        {
            "type": "render",
            "script": """
                const h = React.createElement;

                const severityColors = {
                    High: 'bg-red-100 text-red-700 border-red-200',
                    Medium: 'bg-amber-100 text-amber-700 border-amber-200',
                    Low: 'bg-green-100 text-green-700 border-green-200',
                };

                return h('div', { className: 'space-y-6' },

                    // Phase progress bars
                    h('div', { className: 'bg-white rounded-lg border border-gray-200 p-4' },
                        h('h3', { className: 'text-sm font-semibold text-gray-700 mb-3' }, 'Phase Progress'),
                        h('div', { className: 'space-y-3' },
                            ...data.phases.map(function(phase, i) {
                                return h('div', { key: i },
                                    h('div', { className: 'flex justify-between text-xs mb-1' },
                                        h('span', { className: 'font-medium text-gray-700' }, phase.name),
                                        h('span', { className: 'text-gray-500' }, phase.progress + '%')
                                    ),
                                    h('div', { className: 'w-full bg-gray-100 rounded-full h-2.5' },
                                        h('div', {
                                            className: 'h-2.5 rounded-full transition-all',
                                            style: { width: phase.progress + '%', backgroundColor: phase.color }
                                        })
                                    )
                                );
                            })
                        )
                    ),

                    // Two-column layout: risks + team
                    h('div', { className: 'grid grid-cols-2 gap-4' },

                        // Risk register
                        h('div', { className: 'bg-white rounded-lg border border-gray-200 p-4' },
                            h('h3', { className: 'text-sm font-semibold text-gray-700 mb-3' }, 'Risk Register'),
                            h('div', { className: 'space-y-2' },
                                ...data.risks.map(function(risk, i) {
                                    return h('div', {
                                        key: i,
                                        className: 'flex items-center gap-2 p-2 rounded border ' + (severityColors[risk.severity] || '')
                                    },
                                        h('span', { className: 'text-xs font-bold' }, risk.id),
                                        h('span', { className: 'text-xs flex-1' }, risk.title),
                                        h('span', { className: 'text-xs opacity-75' }, risk.owner)
                                    );
                                })
                            )
                        ),

                        // Team workload
                        h('div', { className: 'bg-white rounded-lg border border-gray-200 p-4' },
                            h('h3', { className: 'text-sm font-semibold text-gray-700 mb-3' }, 'Team Workload'),
                            h('div', { className: 'space-y-2' },
                                ...data.team.map(function(member, i) {
                                    var maxTasks = 20;
                                    var pct = Math.min(100, (member.tasks / maxTasks) * 100);
                                    return h('div', { key: i, className: 'flex items-center gap-3' },
                                        h('div', { className: 'w-20 text-xs' },
                                            h('div', { className: 'font-medium text-gray-700' }, member.name),
                                            h('div', { className: 'text-gray-400' }, member.role)
                                        ),
                                        h('div', { className: 'flex-1 bg-gray-100 rounded-full h-2' },
                                            h('div', {
                                                className: 'h-2 rounded-full bg-indigo-500',
                                                style: { width: pct + '%' }
                                            })
                                        ),
                                        h('span', { className: 'text-xs text-gray-500 w-8 text-right' },
                                            member.tasks
                                        )
                                    );
                                })
                            )
                        )
                    )
                );
            """,
        },
    ],
)

print("Project dashboard generated with custom JS render function.")
