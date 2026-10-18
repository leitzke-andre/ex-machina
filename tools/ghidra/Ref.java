import ghidra.app.script.GhidraScript;
import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
public class Ref extends GhidraScript {
  public void run() throws Exception {
    FunctionManager fm=currentProgram.getFunctionManager();
    println("FUNCS "+fm.getFunctionCount());
    String[] n={"devdesc","cfgdesc","hidrpt","strtab"};
    long[] a={0x08008d5cL,0x08008d66L,0x08008e4cL,0x08008da0L};
    for(int i=0;i<n.length;i++){
      ReferenceIterator it=currentProgram.getReferenceManager().getReferencesTo(toAddr(a[i]));
      StringBuilder sb=new StringBuilder();
      while(it.hasNext()){Reference r=it.next();Function f=fm.getFunctionContaining(r.getFromAddress());sb.append(r.getFromAddress()+"@"+(f==null?"-":f.getName())+" ");}
      println("REF "+n[i]+" "+sb);
    }
    // literal pool word scan for cfg pointer
  }
}
