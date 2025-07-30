import os
import zipfile
import tempfile
import shutil
import json
from datetime import datetime

def create_project_structure(temp_dir):
    """Create the basic Gradle project structure"""
    # Create main project directory
    root_dir = os.path.join(temp_dir, 'e2e-test-suite')
    os.makedirs(root_dir)
    
    # Create source directories
    src_test_java = os.path.join(root_dir, 'src', 'test', 'java', 'com', 'upgrad', 'e2e')
    os.makedirs(src_test_java)
    
    # Create resources directory for feature files
    features_dir = os.path.join(root_dir, 'src', 'test', 'resources', 'FeatureFiles', 'Web')
    os.makedirs(features_dir)
    
    # Create build.gradle
    with open(os.path.join(root_dir, 'build.gradle'), 'w') as f:
        f.write('''
plugins {
    id 'java'
}

repositories {
    mavenCentral()
}

dependencies {
    testImplementation 'org.seleniumhq.selenium:selenium-java:4.1.0'
    testImplementation 'io.cucumber:cucumber-java:6.10.4'
    testImplementation 'io.cucumber:cucumber-junit:6.10.4'
    testImplementation 'junit:junit:4.13.2'
}
''')
    
    # Create settings.gradle
    with open(os.path.join(root_dir, 'settings.gradle'), 'w') as f:
        f.write("rootProject.name = 'e2e-test-suite'\n")
    
    return root_dir

def generate_feature_files(test_suite, temp_dir):
    """Generate Cucumber feature files from test suite"""
    features_dir = os.path.join(temp_dir, 'e2e-test-suite', 'src', 'test', 'resources', 'FeatureFiles', 'Web')
    
    for idx, step in enumerate(test_suite):
        feature_file = os.path.join(features_dir, f'TestFlow_{idx+1}.feature')
        with open(feature_file, 'w') as f:
            f.write(f'Feature: {step.get("testName", f"Test Flow {idx+1}")}\n\n')
            f.write('  Scenario: Execute test flow\n')
            
            for substep in step.get('steps', []):
                action = substep.get('action', 'step')
                desc = substep.get('description', '')
                
                if action == 'click':
                    f.write(f'    When I click on {desc}\n')
                elif action == 'type':
                    f.write(f'    When I type "<text>" into {desc}\n')
                elif action == 'assert':
                    f.write(f'    Then I should see "<expected>" in {desc}\n')
                elif action == 'wait':
                    f.write(f'    And I wait for <ms> ms\n')
                elif action == 'select':
                    f.write(f'    When I select "<option>" from {desc}\n')
                else:
                    f.write(f'    And {desc}\n')

def generate_page_objects(test_suite, temp_dir, mode):
    """Generate Page Object classes for each UI step"""
    src_test_java = os.path.join(temp_dir, 'e2e-test-suite', 'src', 'test', 'java', 'com', 'upgrad', 'e2e')
    
    for idx, step in enumerate(test_suite):
        page_file = os.path.join(src_test_java, f'Page_{idx+1}.java')
        with open(page_file, 'w') as f:
            f.write(f'''
package com.upgrad.e2e;

import org.openqa.selenium.*;
import org.openqa.selenium.support.ui.WebDriverWait;
import org.openqa.selenium.support.ui.ExpectedConditions;
import java.time.Duration;

public class Page_{idx+1} {{
    private WebDriver driver;
    private WebDriverWait wait;
    
    public Page_{idx+1}(WebDriver driver) {{
        this.driver = driver;
        this.wait = new WebDriverWait(driver, Duration.ofSeconds(10));
    }}
    
    // Add page-specific methods here based on the step actions
    public void clickElement(String selector) {{
        wait.until(ExpectedConditions.elementToBeClickable(By.xpath(selector))).click();
    }}
    
    public void typeText(String selector, String text) {{
        wait.until(ExpectedConditions.visibilityOfElementLocated(By.xpath(selector))).sendKeys(text);
    }}
    
    public void assertText(String selector, String expectedText) {{
        String actualText = wait.until(ExpectedConditions.visibilityOfElementLocated(By.xpath(selector))).getText();
        if (!actualText.contains(expectedText)) {{
            throw new AssertionError("Expected text not found: " + expectedText);
        }}
    }}
}}
''')

def generate_step_definitions(test_suite, temp_dir, mode):
    """Generate Step Definition classes"""
    src_test_java = os.path.join(temp_dir, 'e2e-test-suite', 'src', 'test', 'java', 'com', 'upgrad', 'e2e')
    
    step_def_file = os.path.join(src_test_java, 'StepDefinitions.java')
    with open(step_def_file, 'w') as f:
        f.write('''
package com.upgrad.e2e;

import io.cucumber.java.en.*;
import org.openqa.selenium.*;
import org.openqa.selenium.chrome.ChromeDriver;
import org.junit.*;
import java.time.Duration;

public class StepDefinitions {
    private WebDriver driver;
    
    @Before
    public void setUp() {
        driver = new ChromeDriver();
        driver.manage().window().maximize();
        driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(10));
    }
    
    @After
    public void tearDown() {
        if (driver != null) {
            driver.quit();
        }
    }
    
    @When("I click on {string}")
    public void i_click_on(String selector) {
        new WebDriverWait(driver, Duration.ofSeconds(10))
            .until(ExpectedConditions.elementToBeClickable(By.xpath(selector)))
            .click();
    }
    
    @When("I type {string} into {string}")
    public void i_type_into(String text, String selector) {
        new WebDriverWait(driver, Duration.ofSeconds(10))
            .until(ExpectedConditions.visibilityOfElementLocated(By.xpath(selector)))
            .sendKeys(text);
    }
    
    @Then("I should see {string} in {string}")
    public void i_should_see_in(String expectedText, String selector) {
        String actualText = new WebDriverWait(driver, Duration.ofSeconds(10))
            .until(ExpectedConditions.visibilityOfElementLocated(By.xpath(selector)))
            .getText();
        Assert.assertTrue("Expected text not found: " + expectedText, 
                         actualText.contains(expectedText));
    }
    
    @And("I wait for {int} ms")
    public void i_wait_for_ms(int milliseconds) throws InterruptedException {
        Thread.sleep(milliseconds);
    }
    
    @When("I select {string} from {string}")
    public void i_select_from(String option, String selector) {
        new org.openqa.selenium.support.ui.Select(
            new WebDriverWait(driver, Duration.ofSeconds(10))
                .until(ExpectedConditions.visibilityOfElementLocated(By.xpath(selector)))
        ).selectByVisibleText(option);
    }
}
''')

def generate_api_hooks(test_suite, temp_dir, mode):
    """Generate API setup/teardown hooks"""
    src_test_java = os.path.join(temp_dir, 'e2e-test-suite', 'src', 'test', 'java', 'com', 'upgrad', 'e2e')
    
    hooks_file = os.path.join(src_test_java, 'ApiHooks.java')
    with open(hooks_file, 'w') as f:
        f.write('''
package com.upgrad.e2e;

import io.cucumber.java.Before;
import io.cucumber.java.After;
import org.junit.AfterClass;
import org.junit.BeforeClass;

public class ApiHooks {
    @BeforeClass
    public static void setUp() {
        // Add API setup logic here
        System.out.println("Setting up API test environment");
    }
    
    @AfterClass
    public static void tearDown() {
        // Add API teardown logic here
        System.out.println("Cleaning up API test environment");
    }
}
''')

def create_gradle_zip(test_suite, mode='general'):
    """Create a zip file containing a complete Gradle project with all test files"""
    try:
        # Create a temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create project structure
            create_project_structure(temp_dir)
            
            # Generate feature files
            generate_feature_files(test_suite, temp_dir)
            
            # Generate page objects
            generate_page_objects(test_suite, temp_dir, mode)
            
            # Generate step definitions
            generate_step_definitions(test_suite, temp_dir, mode)
            
            # Generate API hooks
            generate_api_hooks(test_suite, temp_dir, mode)
            
            # Create zip file
            zip_path = os.path.join(temp_dir, 'test-suite.zip')
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(temp_dir):
                    for file in files:
                        if file != 'test-suite.zip':  # Don't include the zip file itself
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, temp_dir)
                            zipf.write(file_path, arcname)
            
            with open(zip_path, 'rb') as f:
                zip_bytes = f.read()
            return zip_bytes
    except Exception as e:
        print(f"Error creating zip file: {str(e)}")
        raise
