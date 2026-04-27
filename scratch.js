const fs = require('fs');
const metadata = JSON.parse(fs.readFileSync('tailored_resumes/boozallen/universityapplied_ai_intern/metadata.json'));
const res_json = metadata;
const allChanges = [
  ...(res_json?.experience || []).flatMap(exp => 
    exp.bullets.map(b => ({ b, title: exp.role || exp.company }))
  ),
  ...(res_json?.projects || []).flatMap(prj => 
    prj.bullets.map(b => ({ b, title: prj.name }))
  )
];
console.log(allChanges[0]);
