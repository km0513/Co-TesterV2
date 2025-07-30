/**
 * UI Recorder JavaScript
 * Simple bookmarklet for recording UI interactions
 */

function startRecording() {
  // Create UI
  var d = document.createElement('div');
  d.style.position = 'fixed';
  d.style.top = '0';
  d.style.right = '0';
  d.style.zIndex = '9999999';
  d.style.background = 'red';
  d.style.color = 'white';
  d.style.padding = '10px';
  d.innerHTML = '🔴 Recording';
  document.body.appendChild(d);
  
  // Store actions
  var acts = [];
  
  // Record navigation
  acts.push({type:'nav', url:location.href});
  
  // Record clicks
  document.addEventListener('click', function(e){
    var t = e.target;
    var s = t.id ? '#'+t.id : t.tagName;
    acts.push({type:'click', sel:s, txt:t.innerText});
    d.innerHTML = '🔴 Click recorded';
    setTimeout(function(){d.innerHTML='🔴 Recording';}, 1000);
  }, true);
  
  // Stop button
  var b = document.createElement('button');
  b.innerHTML = 'Stop';
  b.style.marginLeft = '10px';
  b.onclick = function(){
    var w = window.open();
    w.document.write('<h1>Recorded Actions</h1><pre>'+JSON.stringify(acts,null,2)+'</pre>');
    w.document.write('<h1>Java Code</h1><pre>'+genCode(acts)+'</pre>');
    document.body.removeChild(d);
  };
  d.appendChild(b);
  
  // Generate code
  function genCode(a){
    var c = 'import org.openqa.selenium.*;\n';
    c += 'import org.openqa.selenium.chrome.ChromeDriver;\n\n';
    c += 'public class UiTest {\n';
    c += '    public static void main(String[] args) {\n';
    c += '        WebDriver driver = new ChromeDriver();\n';
    
    a.forEach(function(x){
      if(x.type == 'nav') {
        c += '        driver.get("'+x.url+'");\n';
      } else if(x.type == 'click') {
        c += '        driver.findElement(By.cssSelector("'+x.sel+'")).click();\n';
      }
    });
    
    c += '        driver.quit();\n';
    c += '    }\n';
    c += '}';
    return c;
  }

  return 'Recording started!';
} 