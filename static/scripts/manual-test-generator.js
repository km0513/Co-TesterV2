// Replace mockGenerateTestCases with real API call
async function generateTestCases(scenarioText) {
    const res = await fetch('/api/generate-testcases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario: scenarioText })
    });
    const data = await res.json();
    if (data.testcases) return data.testcases;
    alert(data.error || 'Failed to generate test cases');
    return [];
}

generateBtn.onclick = async function() {
    const scenarioText = document.getElementById('scenarioInput').value.trim();
    if (!scenarioText) {
        alert('Please enter a scenario or Jira story.');
        return;
    }
    document.getElementById('loading').style.display = 'block';
    currentTestCases = await generateTestCases(scenarioText);
    renderTestCases(currentTestCases);
    document.getElementById('testcasesSection').style.display = 'block';
    document.getElementById('loading').style.display = 'none';
}; 