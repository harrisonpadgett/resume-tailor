const fs = require('fs');

// Read the metadata.json
const metadata = JSON.parse(fs.readFileSync('../tailored_resumes/boozallen/universityapplied_ai_intern/metadata.json', 'utf8'));

// Emulate tailorResult.res_json
const res_json = metadata;

const allChanges = [
  ...(res_json?.experience || []).flatMap(exp => 
    exp.bullets.map(b => ({ b, title: exp.role || exp.company }))
  ),
  ...(res_json?.projects || []).flatMap(prj => 
    prj.bullets.map(b => ({ b, title: prj.name }))
  )
];

// Replicate mapping logic exactly as in App.jsx
const elements = allChanges.map(({ b, title }, i) => {
  if (!b) return null;
  if (b.original === b.tailored && !b.rationale.includes("REJECTED")) return null;

  const isRejected = b.rationale.includes("REJECTED");
  
  return {
      title,
      isRejected,
      hasDiff: !isRejected,
      originalText: b.original,
      tailoredText: b.tailored,
      rationale: b.rationale
  };
});

console.log(JSON.stringify(elements.filter(e => e !== null), null, 2));
