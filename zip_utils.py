import zipfile
import io
import json
from datetime import datetime

def create_gradle_zip(test_data, mode='e2e'):
    """Create a ZIP file with Gradle project structure for test automation"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Add basic Gradle structure
        zip_file.writestr('build.gradle', create_build_gradle())
        zip_file.writestr('gradle.properties', create_gradle_properties())
        zip_file.writestr('settings.gradle', 'rootProject.name = "automated-tests"')
        
        # Add test files
        for i, test in enumerate(test_data):
            test_name = test.get('testName', f'Test_{i+1}')
            safe_name = "".join(c for c in test_name if c.isalnum() or c in (' ', '_')).rstrip()
            safe_name = safe_name.replace(' ', '_')
            
            test_content = generate_test_content(test, mode)
            zip_file.writestr(f'src/test/java/{safe_name}Test.java', test_content)
    
    zip_buffer.seek(0)
    return zip_buffer.getvalue()

def create_build_gradle():
    return '''plugins {
    id 'java'
    id 'io.qameta.allure' version '2.11.2'
}

group = 'com.automation'
version = '1.0.0'

repositories {
    mavenCentral()
}

dependencies {
    testImplementation 'org.junit.jupiter:junit-jupiter:5.9.2'
    testImplementation 'io.rest-assured:rest-assured:5.3.0'
    testImplementation 'com.microsoft.playwright:playwright:1.40.0'
    testImplementation 'io.qameta.allure:allure-junit5:2.21.0'
    testImplementation 'org.slf4j:slf4j-simple:2.0.6'
}

test {
    useJUnitPlatform()
    systemProperty 'junit.jupiter.extensions.autodetection.enabled', true
}
'''

def create_gradle_properties():
    return '''org.gradle.jvmargs=-Xmx2048m
org.gradle.parallel=true
org.gradle.caching=true
'''

def generate_test_content(test, mode):
    test_name = test.get('testName', 'GeneratedTest')
    safe_name = "".join(c for c in test_name if c.isalnum() or c in (' ', '_')).rstrip()
    safe_name = safe_name.replace(' ', '_')
    
    return f'''package com.automation.tests;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import static org.junit.jupiter.api.Assertions.*;

public class {safe_name}Test {{
    
    @Test
    @DisplayName("{test_name}")
    public void {safe_name.lower()}() {{
        // Generated test case: {test_name}
        // TODO: Implement test logic
        assertTrue(true, "Test placeholder - implement actual test logic");
    }}
}}
'''