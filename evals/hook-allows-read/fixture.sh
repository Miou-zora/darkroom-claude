#!/bin/bash
# Seeds the empty eval workspace with a sidecar holding two history entries. Runs only with --scaffold.
cat > DSC0412.ARW.xmp <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 4.4.0-Exiv2">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:darktable="http://darktable.sf.net/"
   darktable:xmp_version="5"
   darktable:history_end="2">
   <darktable:history>
    <rdf:Seq>
     <rdf:li darktable:num="0" darktable:operation="exposure" darktable:enabled="1" darktable:modversion="7" darktable:params="00" darktable:multi_name="" darktable:multi_priority="0"/>
     <rdf:li darktable:num="1" darktable:operation="sigmoid" darktable:enabled="1" darktable:modversion="3" darktable:params="00" darktable:multi_name="" darktable:multi_priority="0"/>
    </rdf:Seq>
   </darktable:history>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
EOF
