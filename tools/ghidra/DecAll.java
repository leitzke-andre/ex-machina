import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.*;
import java.io.*;
import java.util.*;
public class DecAll extends GhidraScript {
  public void run() throws Exception {
    String[] args=getScriptArgs();
    List<String> lines=java.nio.file.Files.readAllLines(new File(args[0]).toPath());
    PrintWriter out=new PrintWriter(new FileWriter(args[1]));
    FunctionManager fm=currentProgram.getFunctionManager();
    Register tm=currentProgram.getLanguage().getRegister("TMode");
    DecompInterface di=new DecompInterface(); di.openProgram(currentProgram);
    TreeMap<Long,Function> done=new TreeMap<>();
    for(String l:lines){ l=l.trim(); if(l.isEmpty()) continue;
      long a=Long.parseLong(l,16);
      Address ad=toAddr(a);
      Function f=fm.getFunctionContaining(ad);
      if(f==null){
        // scan back for push {..lr}
        for(long p=a&~1L;p>a-0x400;p-=2){
          int h=currentProgram.getMemory().getShort(toAddr(p))&0xffff;
          if((h&0xff00)==0xb500){ Address pa=toAddr(p);
            try{ currentProgram.getProgramContext().setValue(tm,pa,pa,java.math.BigInteger.ONE);}catch(Exception e){}
            disassemble(pa); f=createFunction(pa,null); break; }
        }
      }
      if(f==null){ out.println("//// NO FUNC for "+l); continue; }
      done.put(f.getEntryPoint().getOffset(),f);
    }
    for(Function f:done.values()){
      DecompileResults r=di.decompileFunction(f,60,monitor);
      out.println("//// "+f.getName()+" @ "+f.getEntryPoint()+" size "+f.getBody().getNumAddresses());
      out.println(r.getDecompiledFunction()==null?"(fail)":r.getDecompiledFunction().getC());
    }
    out.close();
  }
}
